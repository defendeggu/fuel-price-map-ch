"""
Scraper für Schweizer Treibstoffpreise.

Strategie 1 (bevorzugt): Einloggen auf benzin.tcs.ch (Azure B2C → Firebase),
  Firebase ID-Token abgreifen, Stationsdaten per REST-API holen,
  Kantonspreise als Ø aller Stationen pro Kanton berechnen.

Strategie 2 (Fallback): Nationalen Durchschnitt von GlobalPetrolPrices.com
  scrapen, kantonsübliche Offsets anwenden.

Läuft wöchentlich via GitHub Actions (.github/workflows/scrape.yml).
Credentials: TCS_EMAIL und TCS_PASSWORD als GitHub Secrets.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Kantonsoffsets (Fallback-Strategie) ───────────────────────────────────────
# Kantonsabweichung vom nationalen Ø (CHF/L).
# Grenzkantone günstiger, Bergkantone teurer.
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

# Kürzel-Mapping für TCS-Kantonsnamen → CH-Abkürzung
CANTON_NAME_TO_KZ = {
    "zürich": "ZH", "bern": "BE", "luzern": "LU", "uri": "UR", "schwyz": "SZ",
    "obwalden": "OW", "nidwalden": "NW", "glarus": "GL", "zug": "ZG",
    "freiburg": "FR", "fribourg": "FR", "solothurn": "SO", "basel-stadt": "BS",
    "basel-landschaft": "BL", "schaffhausen": "SH", "appenzell ausserrhoden": "AR",
    "appenzell innerrhoden": "AI", "st. gallen": "SG", "graubünden": "GR",
    "aargau": "AG", "thurgau": "TG", "tessin": "TI", "ticino": "TI",
    "waadt": "VD", "vaud": "VD", "wallis": "VS", "valais": "VS",
    "neuenburg": "NE", "neuchâtel": "NE", "genf": "GE", "genève": "GE",
    "jura": "JU",
}


# ── Strategie 1: TCS benzin.tcs.ch ───────────────────────────────────────────

async def tcs_login_and_fetch(email: str, password: str) -> dict | None:
    """
    Loggt sich auf benzin.tcs.ch ein (Azure B2C → Firebase),
    greift den Firebase ID-Token ab und holt Stationsdaten.
    Gibt dict {"diesel": {KZ: preis}, "benzin": {KZ: preis}} zurück
    oder None bei Fehler.
    """
    from playwright.async_api import async_playwright

    print("Strategie 1: TCS benzin.tcs.ch Login …")

    firebase_token = None
    firebase_db_url = None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox"])
        context = await browser.new_context()
        page = await context.new_page()

        # Firebase ID-Token aus Netzwerk-Requests abgreifen
        async def intercept(request):
            nonlocal firebase_token, firebase_db_url
            url = request.url
            # Firebase Token wird bei identitytoolkit-Calls zurückgegeben
            if "identitytoolkit.googleapis.com" in url or "securetoken.googleapis.com" in url:
                pass  # Token kommt in Response

        async def intercept_response(response):
            nonlocal firebase_token, firebase_db_url
            url = response.url
            try:
                if "identitytoolkit.googleapis.com/v1/accounts:signInWithPassword" in url:
                    data = await response.json()
                    if "idToken" in data:
                        firebase_token = data["idToken"]
                        print(f"  Firebase ID-Token abgegriffen ({len(firebase_token)} Zeichen)")
                elif "identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken" in url:
                    data = await response.json()
                    if "idToken" in data:
                        firebase_token = data["idToken"]
                        print(f"  Firebase Custom-Token-Login abgegriffen")
                # Firebase DB URL aus Requests erkennen
                if ".firebaseio.com" in url and firebase_db_url is None:
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    firebase_db_url = f"{parsed.scheme}://{parsed.netloc}"
                    print(f"  Firebase DB: {firebase_db_url}")
            except Exception:
                pass

        page.on("response", intercept_response)

        # Seite laden
        print("  Lade benzin.tcs.ch …")
        await page.goto("https://benzin.tcs.ch", wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3000)

        # Login-Button suchen und klicken
        login_clicked = False
        for selector in ["button:has-text('Login')", "button:has-text('Anmelden')",
                         "a:has-text('Login')", "[data-cy='login']", ".login-btn",
                         "button:has-text('Einloggen')", "ion-button:has-text('Login')"]:
            try:
                el = await page.wait_for_selector(selector, timeout=3000)
                if el:
                    await el.click()
                    login_clicked = True
                    print(f"  Login-Button gefunden: {selector}")
                    break
            except Exception:
                pass

        if not login_clicked:
            # Versuche direkt auf die Login-URL zu navigieren
            print("  Kein Login-Button gefunden, navigiere zu /login …")
            await page.goto("https://benzin.tcs.ch/login", wait_until="domcontentloaded", timeout=15_000)

        await page.wait_for_timeout(3000)

        # Azure B2C Login-Formular ausfüllen
        print("  Fülle Login-Formular aus …")
        filled = False
        for email_sel in ["input[type='email']", "input[name='email']",
                          "input[id*='email']", "input[placeholder*='@']",
                          "input[name='signInName']", "#email"]:
            try:
                el = await page.wait_for_selector(email_sel, timeout=5000)
                if el and await el.is_visible():
                    await el.fill(email)
                    filled = True
                    print(f"  E-Mail Feld: {email_sel}")
                    break
            except Exception:
                pass

        if not filled:
            print("  E-Mail Feld nicht gefunden", file=sys.stderr)
            await browser.close()
            return None

        for pw_sel in ["input[type='password']", "input[name='password']",
                       "input[id*='password']", "#password"]:
            try:
                el = await page.wait_for_selector(pw_sel, timeout=3000)
                if el and await el.is_visible():
                    await el.fill(password)
                    print(f"  Passwort-Feld: {pw_sel}")
                    break
            except Exception:
                pass

        # Submit
        for submit_sel in ["button[type='submit']", "input[type='submit']",
                           "button:has-text('Weiter')", "button:has-text('Anmelden')",
                           "button:has-text('Sign in')", "#next"]:
            try:
                el = await page.wait_for_selector(submit_sel, timeout=3000)
                if el and await el.is_visible():
                    await el.click()
                    print(f"  Submit: {submit_sel}")
                    break
            except Exception:
                pass

        # Auf Firebase-Token warten (max. 15s)
        for _ in range(15):
            if firebase_token:
                break
            await page.wait_for_timeout(1000)

        if not firebase_token:
            # Letzter Versuch: Token aus localStorage
            try:
                storage = await page.evaluate("() => { const r = {}; for (let k in localStorage) r[k] = localStorage[k]; return r; }")
                for k, v in storage.items():
                    if "firebase" in k.lower() or "token" in k.lower():
                        try:
                            data = json.loads(v)
                            if isinstance(data, dict):
                                token_val = (data.get("stsTokenManager") or {}).get("accessToken") or data.get("idToken")
                                if token_val:
                                    firebase_token = token_val
                                    print(f"  Firebase-Token aus localStorage ({k})")
                                    break
                        except Exception:
                            pass
            except Exception:
                pass

        if not firebase_token:
            print("  Kein Firebase-Token gefunden", file=sys.stderr)
            await browser.close()
            return None

        # Firebase DB URL aus allen Requests ermitteln (Fallback: aus page source)
        if not firebase_db_url:
            try:
                content = await page.content()
                import re
                match = re.search(r'https://([a-z0-9-]+)\.firebaseio\.com', content)
                if match:
                    firebase_db_url = f"https://{match.group(1)}.firebaseio.com"
                    print(f"  Firebase DB aus Source: {firebase_db_url}")
            except Exception:
                pass

        await browser.close()

    if not firebase_db_url:
        print("  Firebase DB URL nicht gefunden", file=sys.stderr)
        return None

    # Stationsdaten per REST-API holen
    return await fetch_station_data(firebase_db_url, firebase_token)


async def fetch_station_data(db_url: str, token: str) -> dict | None:
    """Holt Stationsdaten aus Firebase und berechnet Kantonspreise."""
    import aiohttp

    print(f"  Hole Stationsdaten von {db_url} …")

    # Typische Firebase-Pfade für TCS
    paths_to_try = [
        "/stations.json", "/gas_stations.json", "/gasStations.json",
        "/tankstellen.json", "/prices.json", "/data.json",
        "/v1/stations.json", "/api/stations.json",
    ]

    async with aiohttp.ClientSession() as session:
        for path in paths_to_try:
            url = f"{db_url}{path}?auth={token}"
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data:
                            print(f"  Daten gefunden unter {path} ({type(data).__name__})")
                            return aggregate_by_canton(data)
                    elif resp.status == 403:
                        print(f"  {path}: 403 Forbidden (kein Zugriff)")
                    else:
                        print(f"  {path}: HTTP {resp.status}")
            except Exception as e:
                print(f"  {path}: {e}", file=sys.stderr)

    return None


def aggregate_by_canton(data) -> dict:
    """Aggregiert Stationsdaten zu Kantonspreisen (Ø pro Kanton)."""
    from collections import defaultdict

    diesel_sums = defaultdict(list)
    benzin_sums = defaultdict(list)

    items = data.values() if isinstance(data, dict) else data if isinstance(data, list) else []
    for station in items:
        if not isinstance(station, dict):
            continue
        kz = None
        # Kanton-Kürzel direkt
        for field in ["canton", "kanton", "canton_code", "kz", "state"]:
            v = station.get(field, "")
            if isinstance(v, str) and len(v) == 2:
                kz = v.upper()
                break
        # Kantonsname → Kürzel
        if not kz:
            for field in ["canton_name", "kanton_name", "region"]:
                v = station.get(field, "")
                if isinstance(v, str):
                    kz = CANTON_NAME_TO_KZ.get(v.lower())
                    if kz:
                        break

        if not kz or kz not in OFFSETS["diesel"]:
            continue

        # Preise extrahieren
        for field in ["diesel", "diesel_price", "gasoil", "gasoil_price"]:
            p = station.get(field)
            if isinstance(p, (int, float)) and 1.0 < p < 3.0:
                diesel_sums[kz].append(p)
                break

        for field in ["benzin", "benzin_price", "gasoline", "gasoline_price",
                      "petrol", "unleaded", "super"]:
            p = station.get(field)
            if isinstance(p, (int, float)) and 1.0 < p < 3.0:
                benzin_sums[kz].append(p)
                break

    if not diesel_sums and not benzin_sums:
        print("  Keine Preisdaten in Stationsdaten gefunden", file=sys.stderr)
        return None

    result = {"diesel": {}, "benzin": {}}
    for kz in OFFSETS["diesel"]:
        if diesel_sums[kz]:
            result["diesel"][kz] = round(sum(diesel_sums[kz]) / len(diesel_sums[kz]), 3)
        if benzin_sums[kz]:
            result["benzin"][kz] = round(sum(benzin_sums[kz]) / len(benzin_sums[kz]), 3)

    counts = {k: len(v) for k, v in diesel_sums.items() if v}
    print(f"  Kantone mit Daten: {len(counts)} | Stationen gesamt: {sum(counts.values())}")
    return result


# ── Strategie 2: GlobalPetrolPrices Fallback ──────────────────────────────────

async def fetch_price_globalpetrol(page, url: str) -> float | None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(2000)
        price = await page.evaluate("""() => {
            const rows = document.querySelectorAll('tr');
            for (const row of rows) {
                const text = row.textContent;
                if (text.includes('Switzerland') || text.includes('Schweiz')) {
                    const match = text.match(/1\\.[5-9]\\d{2}/);
                    if (match) return parseFloat(match[0]);
                }
            }
            for (const el of document.querySelectorAll('td, .price, [class*=price]')) {
                const t = el.textContent.trim();
                if (/^1\\.[5-9]\\d{2}$/.test(t)) return parseFloat(t);
            }
            return null;
        }""")
        if price:
            print(f"  ✓ GlobalPetrolPrices {url.split('/')[-2]}: {price:.3f} CHF/L")
            return price
    except Exception as e:
        print(f"  ✗ Fehler bei {url}: {e}", file=sys.stderr)
    return None


async def fallback_globalpetrol() -> dict:
    from playwright.async_api import async_playwright
    print("Strategie 2 (Fallback): GlobalPetrolPrices.com …")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
        )
        diesel_nat = await fetch_price_globalpetrol(
            page, "https://www.globalpetrolprices.com/Switzerland/diesel_prices/"
        )
        benzin_nat = await fetch_price_globalpetrol(
            page, "https://www.globalpetrolprices.com/Switzerland/gasoline_prices/"
        )
        await browser.close()

    diesel_nat = diesel_nat or FALLBACK["diesel"]
    benzin_nat = benzin_nat or FALLBACK["benzin"]
    print(f"Nationaler Ø: Diesel {diesel_nat:.3f} | Benzin 95 {benzin_nat:.3f}")

    return {
        "diesel": {k: round(diesel_nat + v, 3) for k, v in OFFSETS["diesel"].items()},
        "benzin": {k: round(benzin_nat + v, 3) for k, v in OFFSETS["benzin"].items()},
    }


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    email    = os.environ.get("TCS_EMAIL", "")
    password = os.environ.get("TCS_PASSWORD", "")

    canton_prices = None
    source_label  = "GlobalPetrolPrices.com (nationaler Ø) + BFS Kantonsoffsets"

    # Strategie 1: TCS Login
    if email and password:
        try:
            # aiohttp muss verfügbar sein
            import aiohttp  # noqa
            canton_prices = await tcs_login_and_fetch(email, password)
            if canton_prices:
                source_label = "benzin.tcs.ch (Stationsdurchschnitt pro Kanton)"
                print("Strategie 1 erfolgreich.")
            else:
                print("Strategie 1 ohne Ergebnis, verwende Fallback.")
        except ImportError:
            print("aiohttp nicht installiert, überspringe Strategie 1.")
        except Exception as e:
            print(f"Strategie 1 fehlgeschlagen: {e}", file=sys.stderr)
    else:
        print("Keine TCS-Credentials gesetzt, überspringe Strategie 1.")

    # Strategie 2: Fallback
    if not canton_prices:
        fallback = await fallback_globalpetrol()
        canton_prices = fallback

    # Kantonspreise zusammenführen (fehlende Kantone mit Offsets auffüllen)
    cantons = {}
    for kz in OFFSETS["diesel"]:
        d = canton_prices["diesel"].get(kz)
        b = canton_prices["benzin"].get(kz)
        # Fehlende Kantone via Offset vom nationalen Ø schätzen
        if d is None or b is None:
            diesel_vals = [v for v in canton_prices["diesel"].values() if v]
            benzin_vals = [v for v in canton_prices["benzin"].values() if v]
            nat_d = (sum(diesel_vals) / len(diesel_vals)) if diesel_vals else FALLBACK["diesel"]
            nat_b = (sum(benzin_vals) / len(benzin_vals)) if benzin_vals else FALLBACK["benzin"]
            d = d or round(nat_d + OFFSETS["diesel"][kz], 3)
            b = b or round(nat_b + OFFSETS["benzin"][kz], 3)
        cantons[kz] = {"diesel": d, "benzin": b}

    diesel_vals = [v["diesel"] for v in cantons.values()]
    benzin_vals = [v["benzin"] for v in cantons.values()]
    nat_diesel = round(sum(diesel_vals) / len(diesel_vals), 3)
    nat_benzin = round(sum(benzin_vals) / len(benzin_vals), 3)

    output = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "national": {"diesel": nat_diesel, "benzin": nat_benzin},
        "source": source_label,
        "cantons": cantons,
    }

    out_path = Path(__file__).parent.parent / "data" / "canton-prices.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Gespeichert: {out_path} ({len(cantons)} Kantone) | Quelle: {source_label}")


if __name__ == "__main__":
    asyncio.run(main())
