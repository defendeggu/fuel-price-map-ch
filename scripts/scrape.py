"""
Scraper für Schweizer Treibstoffpreise (benzin.tcs.ch, öffentliche Cloud Function).

Ablauf:
  1. Alle Stationen für Diesel und Benzin 95 abrufen (Zoom 18 → keine Cluster)
  2. Station → Kanton per Koordinate (Point-in-Polygon, siehe cantons.py)
  3. Ausreisser verwerfen (relativ zum Median), Samnaun (zollfrei) ausschliessen
  4. Median pro Kanton → data/canton-prices.json, data/price-history.json

Schlägt der Abruf fehl oder sind die Daten unplausibel, endet das Skript mit
Exit-Code 1 und schreibt nichts (der Workflow wird rot, es gibt keine erfundenen Werte).

Keine Abhängigkeiten ausser der Standardbibliothek.
"""

import json
import re
import statistics
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cantons import CantonLocator  # noqa: E402

CLOUD_FUNCTION_URL = "https://europe-west6-tcs-digitalbackend.cloudfunctions.net/benzinGetStationByBbox"
CH_BBOX = [5.9, 45.8, 10.5, 47.8]  # [west, south, east, north]
CLOUD_ZOOM = 18                     # bei 14 fasste der Dienst ~10 % der Stationen zu Clustern zusammen
FUELS = {"diesel": "DIESEL", "benzin": "SP95"}

ALL_CANTONS = [
    "ZH", "BE", "LU", "UR", "SZ", "OW", "NW", "GL", "ZG", "FR", "SO", "BS", "BL",
    "SH", "AR", "AI", "SG", "GR", "AG", "TG", "TI", "VD", "VS", "NE", "GE", "JU",
]
SOURCE_LABEL = "benzin.tcs.ch (Cloud Function, Median der Stationspreise pro Kanton)"

OUTLIER_FACTOR = 0.4       # Preise > ±40 % vom Landesmedian gelten als Fehleingabe
MIN_STATIONS_TOTAL = 2000  # darunter ist der Abruf unplausibel
MIN_STATIONS_PER_CANTON = 3
MAX_JUMP_VS_PREVIOUS = 0.15  # Landesmedian darf sich ggü. dem letzten Eintrag um max. 15 % ändern


# ── Abruf ────────────────────────────────────────────────────────────────────

def fetch_stations(api_fuel: str) -> list[dict]:
    payload = {
        "zoom": CLOUD_ZOOM,
        "pixelRatio": 1,
        "bbox": CH_BBOX,
        "filters": {"fuel": api_fuel, "brands": []},
    }
    req = urllib.request.Request(
        CLOUD_FUNCTION_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Origin": "https://benzin.tcs.ch"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


# ── Aufbereitung (rein, ohne Netz – wird in tests/ geprüft) ───────────────────

def is_excluded(station: dict) -> bool:
    """Samnaun (PLZ 7563) ist zollfrei und verzerrt den Bündner Wert."""
    return bool(re.search(r"\b7563\b", station.get("formattedAddress", "")))


def aggregate(stations: list[dict], locator: CantonLocator) -> tuple[dict, dict]:
    """
    Gibt ({kanton: median_preis}, {kanton: anzahl_stationen}) zurück.
    Cluster, Stationen ohne Preis, ausserhalb der Schweiz oder mit Ausreisserpreis zählen nicht.
    """
    usable = [
        s for s in stations
        if not s.get("cluster") and isinstance(s.get("price"), (int, float)) and s["price"] > 0
        and not is_excluded(s)
    ]
    if not usable:
        return {}, {}
    national = statistics.median(s["price"] for s in usable)
    lo, hi = national * (1 - OUTLIER_FACTOR), national * (1 + OUTLIER_FACTOR)

    by_canton: dict[str, list[float]] = defaultdict(list)
    for s in usable:
        if not (lo <= s["price"] <= hi):
            continue
        kz = locator.locate(s["latitude"], s["longitude"])
        if kz:
            by_canton[kz].append(round(s["price"], 3))

    prices = {kz: round(statistics.median(v), 3) for kz, v in by_canton.items()
              if len(v) >= MIN_STATIONS_PER_CANTON}
    counts = {kz: len(v) for kz, v in by_canton.items() if kz in prices}
    return prices, counts


def validate(result: dict, previous_national: dict | None) -> list[str]:
    """Gibt eine Liste von Problemen zurück (leer = plausibel)."""
    problems = []
    for fuel in FUELS:
        missing = [kz for kz in ALL_CANTONS if kz not in result[fuel]["prices"]]
        if missing:
            problems.append(f"{fuel}: keine/zu wenige Stationen in {', '.join(missing)}")
        total = sum(result[fuel]["counts"].values())
        if total < MIN_STATIONS_TOTAL:
            problems.append(f"{fuel}: nur {total} Stationen (Minimum {MIN_STATIONS_TOTAL})")
        if previous_national and previous_national.get(fuel) and result[fuel]["prices"]:
            now = statistics.median(result[fuel]["prices"].values())
            prev = previous_national[fuel]
            if abs(now - prev) / prev > MAX_JUMP_VS_PREVIOUS:
                problems.append(f"{fuel}: Landesmedian {now:.3f} weicht stark vom letzten Wert {prev:.3f} ab")
    return problems


def update_history(history: dict, today: str, cantons: dict, keep: int = 400) -> dict:
    entries = history.setdefault("entries", [])
    entry = {"date": today, "source": "tcs", "geo": True, "cantons": cantons}
    for i, e in enumerate(entries):
        if e.get("date") == today:
            entries[i] = entry
            break
    else:
        entries.append(entry)
    entries.sort(key=lambda e: e["date"])
    history["entries"] = entries[-keep:]
    return history


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    out_path = data_dir / "canton-prices.json"
    hist_path = data_dir / "price-history.json"

    locator = CantonLocator()
    result = {}
    for fuel, api_fuel in FUELS.items():
        print(f"Hole {api_fuel} …")
        try:
            stations = fetch_stations(api_fuel)
        except Exception as e:
            print(f"FEHLER beim Abruf von {api_fuel}: {e}", file=sys.stderr)
            return 1
        prices, counts = aggregate(stations, locator)
        print(f"  {len(stations)} Einträge → {sum(counts.values())} Stationen in {len(prices)} Kantonen")
        result[fuel] = {"prices": prices, "counts": counts}

    previous = None
    if out_path.exists():
        try:
            previous = json.loads(out_path.read_text()).get("national")
        except Exception:
            pass

    problems = validate(result, previous)
    if problems:
        print("Daten unplausibel, nichts geschrieben:", file=sys.stderr)
        for p in problems:
            print("  -", p, file=sys.stderr)
        return 1

    cantons = {
        kz: {
            "diesel": result["diesel"]["prices"][kz],
            "benzin": result["benzin"]["prices"][kz],
            "n_diesel": result["diesel"]["counts"][kz],
            "n_benzin": result["benzin"]["counts"][kz],
        }
        for kz in ALL_CANTONS
    }
    now = datetime.now(timezone.utc)
    output = {
        "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "national": {
            fuel: round(statistics.median(result[fuel]["prices"].values()), 3) for fuel in FUELS
        },
        "source": SOURCE_LABEL,
        "cantons": cantons,
    }
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Gespeichert: {out_path} ({len(cantons)} Kantone)")

    history = {"entries": []}
    if hist_path.exists():
        try:
            history = json.loads(hist_path.read_text())
        except Exception:
            pass
    slim = {kz: {"diesel": v["diesel"], "benzin": v["benzin"]} for kz, v in cantons.items()}
    update_history(history, now.strftime("%Y-%m-%d"), slim)
    hist_path.write_text(json.dumps(history, separators=(",", ":"), ensure_ascii=False))
    print(f"Verlauf: {hist_path} ({len(history['entries'])} Einträge)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
