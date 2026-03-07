"""
Scraper für Schweizer Treibstoffpreise.

Strategie 1 (bevorzugt): Login auf benzin.tcs.ch (Azure B2C → Firebase),
  Firestore REST-API mit paginierter Abfrage aller Stationen,
  PLZ → Kanton Mapping, Ø-Preis pro Kanton.

Strategie 2 (Fallback): Nationaler Durchschnitt von GlobalPetrolPrices.com
  + BFS Kantonsoffsets.

Läuft wöchentlich via GitHub Actions.
Credentials: TCS_EMAIL, TCS_PASSWORD als GitHub Secrets.
"""

import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ── Firebase / Firestore Konstanten ──────────────────────────────────────────
FIREBASE_API_KEY = "AIzaSyCQ8f6sXb1gYIiv5rlHKeZ2EVMzC-anzIU"
FIRESTORE_BASE   = "https://firestore.googleapis.com/v1/projects/gas-prices-prod/databases/(default)/documents"

# ── PLZ → Kanton (Schweiz) ───────────────────────────────────────────────────
# Kompakte Range-Liste: (plz_von, plz_bis_inkl, kz)
_PLZ_RANGES = [
    (1000,1299,"VD"),(1300,1462,"VD"),(1463,1509,"FR"),(1510,1564,"VD"),
    (1565,1567,"VD"),(1568,1595,"FR"),(1596,1598,"VD"),(1600,1799,"FR"),
    (1800,1860,"VD"),(1861,1999,"VS"),(2000,2416,"NE"),(2500,2564,"BE"),
    (2565,2579,"BE"),(2580,2599,"BE"),(2600,2799,"BE"),(2800,2999,"JU"),
    (3000,3999,"BE"),(4000,4059,"BS"),(4060,4399,"BL"),(4400,4499,"SO"),
    (4500,4663,"SO"),(4700,4719,"SO"),(4800,4828,"AG"),(4900,4999,"BE"),
    (5000,5736,"AG"),(6000,6057,"LU"),(6060,6086,"OW"),(6102,6174,"LU"),
    (6182,6295,"LU"),(6290,6319,"ZG"),(6340,6356,"ZG"),(6362,6416,"NW"),
    (6400,6430,"SZ"),(6431,6443,"SZ"),(6452,6499,"UR"),(6500,6999,"TI"),
    (7000,7322,"GR"),(7400,7748,"GR"),(8000,8199,"ZH"),(8200,8269,"SH"),
    (8270,8399,"TG"),(8400,8455,"ZH"),(8460,8499,"ZH"),(8500,8599,"TG"),
    (8600,8699,"ZH"),(8700,8749,"ZH"),(8750,8774,"GL"),(8800,8999,"ZH"),
    (9000,9038,"SG"),(9042,9064,"AR"),(9053,9058,"AI"),(9100,9116,"AR"),
    (9200,9249,"TG"),(9300,9315,"SG"),(9320,9327,"TG"),(9400,9499,"SG"),
    (9500,9658,"SG"),
]
_PLZ_MAP: dict[int, str] = {}
for _lo, _hi, _kz in _PLZ_RANGES:
    for _p in range(_lo, _hi + 1):
        _PLZ_MAP[_p] = _kz


def plz_to_canton(address: str) -> str | None:
    m = re.search(r'\b(\d{4})\b', address)
    return _PLZ_MAP.get(int(m.group(1))) if m else None


# ── Kantonsoffsets (Fallback) ─────────────────────────────────────────────────
OFFSETS = {
    "diesel": {
        "BL": -0.026, "AG": -0.022, "SH": -0.018, "SO": -0.017, "BS": -0.015,
        "GE": -0.018, "TI": -0.016, "TG": -0.012, "VS": -0.011, "VD": -0.007,
        "NE": -0.004, "JU": -0.002, "BE": -0.003, "LU": -0.001, "FR":  0.000,
        "ZH":  0.000, "SG":  0.003, "ZG":  0.004, "SZ":  0.006, "AR":  0.005,
        "NW":  0.009, "OW":  0.012, "AI":  0.014, "GL":  0.016, "GR":  0.019, "UR":  0.023,
    },
    "benzin": {
        "BL": -0.023, "AG": -0.019, "SH": -0.016, "SO": -0.015, "BS": -0.014,
        "GE": -0.017, "TI": -0.015, "TG": -0.011, "VS": -0.009, "VD": -0.005,
        "NE": -0.003, "JU": -0.001, "BE": -0.003, "LU":  0.000, "FR":  0.000,
        "ZH":  0.001, "SG":  0.003, "ZG":  0.006, "SZ":  0.008, "AR":  0.006,
        "NW":  0.011, "OW":  0.014, "AI":  0.016, "GL":  0.018, "GR":  0.021, "UR":  0.025,
    },
}
FALLBACK = {"diesel": 1.780, "benzin": 1.711}
ALL_CANTONS = list(OFFSETS["diesel"].keys())


# ── Strategie 1: TCS benzin.tcs.ch ───────────────────────────────────────────

async def tcs_get_firebase_token(email: str, password: str) -> str | None:
    """
    Loggt sich auf benzin.tcs.ch ein via Azure B2C und gibt den Firebase ID-Token zurück.
    Flow: benzin.tcs.ch → Anmelden → TCS-Online-Konto → b2clogin.com → credentials → submit
    """
    from playwright.async_api import async_playwright

    token = None
    print("  Starte Playwright-Login auf benzin.tcs.ch …")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox"])
        context = await browser.new_context()
        page    = await context.new_page()

        async def capture_token(resp):
            nonlocal token
            if "identitytoolkit" in resp.url and "signInWith" in resp.url and not token:
                try:
                    d = await resp.json()
                    if "idToken" in d:
                        token = d["idToken"]
                        print(f"  Firebase Token abgegriffen ({len(token)} Zeichen)")
                except Exception:
                    pass

        page.on("response", capture_token)

        # 1. Startseite
        await page.goto("https://benzin.tcs.ch", wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3000)

        # 2. "Anmelden" → /de/login
        await page.click("button:has-text('Anmelden'), button:has-text('Sich registrieren')")
        await page.wait_for_timeout(2000)

        # 3. "TCS-Online-Konto" → navigiert zu b2clogin.com
        await page.click("button:has-text('TCS-Online-Konto')")
        await page.wait_for_timeout(4000)

        if "b2clogin" not in page.url:
            print(f"  Erwartet b2clogin.com, bin auf: {page.url[:80]}", file=sys.stderr)
            await browser.close()
            return None

        # 4. Credentials eingeben (einzeitiges Formular: email + password sichtbar)
        await page.fill("input#signInName", email)
        await page.fill("input#password",   password)
        await page.click("button[type='submit']")
        print("  Credentials eingegeben, warte auf Firebase-Token …")

        # 5. Auf Token warten (max. 25 Sekunden)
        for _ in range(25):
            if token:
                break
            await asyncio.sleep(1)

        await browser.close()

    return token


async def tcs_fetch_canton_prices(token: str) -> dict | None:
    """
    Holt alle Stationen aus Firestore, mappt PLZ → Kanton,
    gibt dict {"diesel": {KZ: preis}, "benzin": {KZ: preis}} zurück.
    """
    import aiohttp

    headers = {"Authorization": f"Bearer {token}"}
    diesel_by_canton = defaultdict(list)
    benzin_by_canton = defaultdict(list)
    total      = 0
    page_token = None

    print("  Hole Stationsdaten aus Firestore …")

    async with aiohttp.ClientSession() as sess:
        while True:
            url = f"{FIRESTORE_BASE}/stations?pageSize=300&key={FIREBASE_API_KEY}"
            if page_token:
                url += f"&pageToken={page_token}"

            async with sess.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    print(f"  Firestore HTTP {resp.status}", file=sys.stderr)
                    break
                data = await resp.json()

            docs = data.get("documents", [])
            if not docs:
                break

            for doc in docs:
                fields  = doc.get("fields", {})
                address = (fields.get("formattedAddress") or {}).get("stringValue", "")
                canton  = plz_to_canton(address)
                if not canton:
                    continue

                fuel_col = (fields.get("fuelCollection") or {}).get("mapValue", {}).get("fields", {})

                # Diesel
                d_fields = fuel_col.get("DIESEL", {}).get("mapValue", {}).get("fields", {})
                d_price  = (d_fields.get("displayPrice") or {}).get("doubleValue")
                if d_price and 1.0 < d_price < 3.0:
                    diesel_by_canton[canton].append(d_price)

                # Benzin 95 (verschiedene Schlüsselnamen)
                for sp_key in ["SP95", "SUPER", "BLEIFREI95", "RON95", "E10"]:
                    sp_f = fuel_col.get(sp_key, {}).get("mapValue", {}).get("fields", {})
                    sp_p = (sp_f.get("displayPrice") or {}).get("doubleValue")
                    if sp_p and 1.0 < sp_p < 3.0:
                        benzin_by_canton[canton].append(sp_p)
                        break

                total += 1

            page_token = data.get("nextPageToken")
            print(f"    {total} Stationen geladen …", end="\r")
            if not page_token:
                break

    print(f"\n  {total} Stationen geladen | {len(diesel_by_canton)} Kantone mit Diesel-Daten")

    if total < 100:
        print("  Zu wenig Stationen – Strategie 1 ungültig", file=sys.stderr)
        return None

    return {
        "diesel": {kz: round(sum(v)/len(v), 3) for kz, v in diesel_by_canton.items() if v},
        "benzin": {kz: round(sum(v)/len(v), 3) for kz, v in benzin_by_canton.items() if v},
    }


async def strategy_tcs(email: str, password: str) -> tuple[dict | None, str]:
    """Strategie 1: TCS Login + Firestore. Gibt (canton_prices, source) zurück."""
    print("Strategie 1: TCS benzin.tcs.ch …")
    try:
        import aiohttp  # noqa – prüfe Verfügbarkeit
        token = await tcs_get_firebase_token(email, password)
        if not token:
            print("  Kein Token erhalten", file=sys.stderr)
            return None, ""
        prices = await tcs_fetch_canton_prices(token)
        if prices:
            return prices, "benzin.tcs.ch (Stationsdurchschnitt pro Kanton)"
        return None, ""
    except ImportError:
        print("  aiohttp nicht installiert", file=sys.stderr)
        return None, ""
    except Exception as e:
        print(f"  Fehler: {e}", file=sys.stderr)
        return None, ""


# ── Strategie 2: GlobalPetrolPrices Fallback ──────────────────────────────────

async def fetch_price_gpp(page, url: str) -> float | None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(2000)
        price = await page.evaluate("""() => {
            for (const row of document.querySelectorAll('tr')) {
                const t = row.textContent;
                if (t.includes('Switzerland') || t.includes('Schweiz')) {
                    const m = t.match(/1\\.[5-9]\\d{2}/);
                    if (m) return parseFloat(m[0]);
                }
            }
            for (const el of document.querySelectorAll('td,[class*=price]')) {
                const t = el.textContent.trim();
                if (/^1\\.[5-9]\\d{2}$/.test(t)) return parseFloat(t);
            }
            return null;
        }""")
        if price:
            print(f"  ✓ {url.split('/')[-2]}: {price:.3f} CHF/L")
            return price
    except Exception as e:
        print(f"  ✗ {url}: {e}", file=sys.stderr)
    return None


async def strategy_fallback() -> tuple[dict, str]:
    """Strategie 2: GlobalPetrolPrices + Kantonsoffsets."""
    from playwright.async_api import async_playwright
    print("Strategie 2 (Fallback): GlobalPetrolPrices.com …")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox"])
        page    = await browser.new_page(user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
        ))
        d = await fetch_price_gpp(page, "https://www.globalpetrolprices.com/Switzerland/diesel_prices/")
        b = await fetch_price_gpp(page, "https://www.globalpetrolprices.com/Switzerland/gasoline_prices/")
        await browser.close()

    d = d or FALLBACK["diesel"]
    b = b or FALLBACK["benzin"]
    print(f"  Nationaler Ø: Diesel {d:.3f} | Benzin 95 {b:.3f}")

    prices = {
        "diesel": {kz: round(d + OFFSETS["diesel"][kz], 3) for kz in ALL_CANTONS},
        "benzin": {kz: round(b + OFFSETS["benzin"][kz], 3) for kz in ALL_CANTONS},
    }
    return prices, "GlobalPetrolPrices.com (nationaler Ø) + BFS Kantonsoffsets"


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    email    = os.environ.get("TCS_EMAIL", "")
    password = os.environ.get("TCS_PASSWORD", "")

    canton_prices = None
    source_label  = ""

    if email and password:
        canton_prices, source_label = await strategy_tcs(email, password)
        if canton_prices:
            print("Strategie 1 erfolgreich.")
        else:
            print("Strategie 1 ohne Ergebnis, verwende Fallback.")
    else:
        print("Keine TCS-Credentials, überspringe Strategie 1.")

    if not canton_prices:
        canton_prices, source_label = await strategy_fallback()

    # Fehlende Kantone mit Offset-Schätzung auffüllen
    cantons: dict[str, dict] = {}
    d_vals = list(canton_prices["diesel"].values())
    b_vals = list(canton_prices["benzin"].values())
    nat_d  = round(sum(d_vals) / len(d_vals), 3) if d_vals else FALLBACK["diesel"]
    nat_b  = round(sum(b_vals) / len(b_vals), 3) if b_vals else FALLBACK["benzin"]

    for kz in ALL_CANTONS:
        d = canton_prices["diesel"].get(kz) or round(nat_d + OFFSETS["diesel"][kz], 3)
        b = canton_prices["benzin"].get(kz) or round(nat_b + OFFSETS["benzin"][kz], 3)
        cantons[kz] = {"diesel": d, "benzin": b}

    all_d  = [v["diesel"] for v in cantons.values()]
    all_b  = [v["benzin"] for v in cantons.values()]

    output = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "national": {
            "diesel": round(sum(all_d) / len(all_d), 3),
            "benzin": round(sum(all_b) / len(all_b), 3),
        },
        "source": source_label,
        "cantons": cantons,
    }

    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)

    # canton-prices.json (aktueller Stand)
    out_path = data_dir / "canton-prices.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Gespeichert: {out_path} ({len(cantons)} Kantone) | {source_label}")

    # price-history.json (akkumulierter Verlauf)
    today_str    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hist_path    = data_dir / "price-history.json"
    source_short = "tcs" if "tcs" in source_label.lower() else "estimated"

    history = {"entries": []}
    if hist_path.exists():
        try:
            history = json.loads(hist_path.read_text())
        except Exception:
            pass

    # Heutigen Eintrag ersetzen oder anhängen
    entries   = history.setdefault("entries", [])
    today_idx = next((i for i, e in enumerate(entries) if e.get("date") == today_str), None)
    new_entry = {"date": today_str, "source": source_short, "cantons": cantons}
    if today_idx is not None:
        entries[today_idx] = new_entry
    else:
        entries.append(new_entry)

    # Chronologisch sortieren, max. 400 Einträge (> 1 Jahr) behalten
    entries.sort(key=lambda e: e["date"])
    history["entries"] = entries[-400:]

    hist_path.write_text(json.dumps(history, separators=(",", ":"), ensure_ascii=False))
    print(f"Verlauf: {hist_path} ({len(history['entries'])} Einträge)")


if __name__ == "__main__":
    asyncio.run(main())
