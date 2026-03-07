"""
Scraper für Schweizer Treibstoffpreise.

Holt den nationalen Durchschnittspreis von GlobalPetrolPrices.com via Playwright
(Headless-Browser nötig, da Seite JS-gerendert ist), wendet kantonsübliche
Offsets an (basierend auf BFS-Regionalfaktoren) und speichert das Ergebnis
als data/canton-prices.json.

Läuft wöchentlich via GitHub Actions (.github/workflows/scrape.yml).
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Kantonsoffsets relativ zum nationalen Durchschnitt (CHF/L).
# Quellen: TCS Benzinpreis-Radar Kantonsvergleiche, BFS Regionalauswertungen.
# Grenzkantone (GE, TI, BL, BS): höhere Tankstellendichte → tendenziell günstiger.
# Bergkantone (UR, GR, GL, AI): Logistikkosten → tendenziell teurer.
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

# Fallbackwerte falls Scraping fehlschlägt
FALLBACK = {"diesel": 1.780, "benzin": 1.711}


async def fetch_price(page, url: str) -> float | None:
    """Lädt eine GlobalPetrolPrices-Seite und extrahiert den aktuellen CH-Preis."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(2000)  # JS-Rendering abwarten

        price = await page.evaluate("""() => {
            // Strategie 1: Tabellenzeile mit Schweiz suchen
            const rows = document.querySelectorAll('tr');
            for (const row of rows) {
                const text = row.textContent;
                if (text.includes('Switzerland') || text.includes('Schweiz')) {
                    const match = text.match(/1\\.[5-9]\\d{2}/);
                    if (match) return parseFloat(match[0]);
                }
            }
            // Strategie 2: Alle Zellen nach Preis-Pattern durchsuchen
            for (const el of document.querySelectorAll('td, .price, [class*=price]')) {
                const t = el.textContent.trim();
                if (/^1\\.[5-9]\\d{2}$/.test(t)) return parseFloat(t);
            }
            return null;
        }""")

        if price:
            print(f"  ✓ {url.split('/')[-2]}: {price:.3f} CHF/L")
            return price

    except Exception as e:
        print(f"  ✗ Fehler bei {url}: {e}", file=sys.stderr)

    return None


async def main():
    from playwright.async_api import async_playwright

    print("Starte Playwright-Scraper …")

    diesel_nat = None
    benzin_nat = None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "Chrome/122.0.0.0 Safari/537.36"
        )

        diesel_nat = await fetch_price(
            page, "https://www.globalpetrolprices.com/Switzerland/diesel_prices/"
        )
        benzin_nat = await fetch_price(
            page, "https://www.globalpetrolprices.com/Switzerland/gasoline_prices/"
        )

        await browser.close()

    # Fallback
    if not diesel_nat:
        print(f"  → Diesel-Fallback: {FALLBACK['diesel']}", file=sys.stderr)
        diesel_nat = FALLBACK["diesel"]
    if not benzin_nat:
        print(f"  → Benzin-Fallback: {FALLBACK['benzin']}", file=sys.stderr)
        benzin_nat = FALLBACK["benzin"]

    print(f"Nationaler Durchschnitt: Diesel {diesel_nat:.3f} | Benzin 95 {benzin_nat:.3f}")

    # Kantonspreise berechnen
    cantons = {}
    for canton in OFFSETS["diesel"]:
        cantons[canton] = {
            "diesel": round(diesel_nat + OFFSETS["diesel"][canton], 3),
            "benzin": round(benzin_nat + OFFSETS["benzin"][canton], 3),
        }

    output = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "national": {"diesel": diesel_nat, "benzin": benzin_nat},
        "source": "GlobalPetrolPrices.com (nationaler Ø) + BFS Kantonsoffsets",
        "cantons": cantons,
    }

    out_path = Path(__file__).parent.parent / "data" / "canton-prices.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Gespeichert: {out_path} ({len(cantons)} Kantone)")


if __name__ == "__main__":
    asyncio.run(main())
