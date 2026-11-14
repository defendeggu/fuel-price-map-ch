"""Unit-Tests für Kantonszuordnung und Aggregation (ohne Netz).  Ausführen: python -m unittest discover -s tests"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import scrape  # noqa: E402
from cantons import CantonLocator  # noqa: E402

LOCATOR = CantonLocator()


class Zuordnung(unittest.TestCase):
    def test_orte_die_die_plz_tabelle_falsch_hatte(self):
        faelle = {
            "Genf": (46.2044, 6.1432, "GE"),
            "Brig": (46.3157, 7.9886, "VS"),
            "Zermatt": (46.0207, 7.7491, "VS"),
            "Appenzell": (47.3305, 9.4094, "AI"),
            "Einsiedeln": (47.1274, 8.7437, "SZ"),
            "Murten": (46.9266, 7.1131, "FR"),
            "Rheinfelden": (47.5539, 7.7936, "AG"),
            "Rapperswil": (47.2266, 8.8225, "SG"),
            "Engelberg": (46.8213, 8.4064, "OW"),
        }
        for name, (lat, lon, soll) in faelle.items():
            with self.subTest(name):
                self.assertEqual(LOCATOR.locate(lat, lon), soll)

    def test_ausland_wird_verworfen(self):
        self.assertIsNone(LOCATOR.locate(47.141, 9.521))    # Vaduz (FL)
        self.assertIsNone(LOCATOR.locate(47.5031, 9.7471))  # Bregenz (AT)
        self.assertIsNone(LOCATOR.locate(47.5988, 7.5373))  # EuroAirport (FR-Seite)

    def test_alle_26_kantone_vorhanden(self):
        self.assertEqual(sorted(LOCATOR.cantons), sorted(scrape.ALL_CANTONS))


def st(price, lat, lon, addr="Teststrasse 1, 8000 Zürich", **kw):
    return {"price": price, "latitude": lat, "longitude": lon, "formattedAddress": addr, "cluster": False, **kw}


class Aggregation(unittest.TestCase):
    ZH = (47.3769, 8.5417)
    GE = (46.2044, 6.1432)

    def test_median_statt_mittelwert(self):
        stations = [st(p, *self.ZH) for p in (2.0, 2.1, 2.2, 2.3, 2.4)] + [st(2.9, *self.ZH)]
        prices, counts = scrape.aggregate(stations, LOCATOR)
        self.assertEqual(prices["ZH"], 2.25)
        self.assertEqual(counts["ZH"], 6)

    def test_ausreisser_relativ_zum_median(self):
        stations = [st(2.3, *self.ZH) for _ in range(5)] + [st(4.5, *self.ZH), st(0.5, *self.ZH)]
        prices, counts = scrape.aggregate(stations, LOCATOR)
        self.assertEqual(counts["ZH"], 5)
        self.assertEqual(prices["ZH"], 2.3)

    def test_hohe_preise_sind_nicht_mehr_abgeschnitten(self):
        # früher: harte Obergrenze 3.0 CHF
        stations = [st(3.2, *self.ZH) for _ in range(5)]
        prices, _ = scrape.aggregate(stations, LOCATOR)
        self.assertEqual(prices["ZH"], 3.2)

    def test_cluster_und_preislose_stationen_zaehlen_nicht(self):
        stations = [st(2.3, *self.ZH) for _ in range(3)]
        stations += [st(2.0, *self.ZH, cluster=True), {"latitude": 47.3, "longitude": 8.5, "cluster": False}]
        _, counts = scrape.aggregate(stations, LOCATOR)
        self.assertEqual(counts["ZH"], 3)

    def test_samnaun_wird_ausgeschlossen(self):
        gr = (46.95, 10.37)
        stations = [st(2.3, *gr, addr="Dorfstrasse 1, 7563 Samnaun")] * 5
        prices, _ = scrape.aggregate(stations, LOCATOR)
        self.assertNotIn("GR", prices)

    def test_kanton_mit_zu_wenig_stationen_hat_keinen_wert(self):
        stations = [st(2.3, *self.ZH) for _ in range(5)] + [st(2.3, *self.GE) for _ in range(2)]
        prices, _ = scrape.aggregate(stations, LOCATOR)
        self.assertIn("ZH", prices)
        self.assertNotIn("GE", prices)


class Validierung(unittest.TestCase):
    def _result(self, n=100, price=2.3, skip=()):
        prices = {kz: price for kz in scrape.ALL_CANTONS if kz not in skip}
        counts = {kz: n for kz in prices}
        return {f: {"prices": dict(prices), "counts": dict(counts)} for f in scrape.FUELS}

    def test_plausibel(self):
        self.assertEqual(scrape.validate(self._result(), {"diesel": 2.32, "benzin": 2.25}), [])

    def test_fehlender_kanton(self):
        self.assertTrue(scrape.validate(self._result(skip=("GE",)), None))

    def test_zu_wenig_stationen(self):
        self.assertTrue(scrape.validate(self._result(n=5), None))

    def test_sprung_zum_vortag(self):
        self.assertTrue(scrape.validate(self._result(price=1.78), {"diesel": 2.32, "benzin": 2.25}))


class Verlauf(unittest.TestCase):
    def test_tageseintrag_wird_ersetzt_und_sortiert(self):
        h = {"entries": [{"date": "2026-01-02", "cantons": {}}, {"date": "2026-01-01", "cantons": {}}]}
        scrape.update_history(h, "2026-01-02", {"ZH": {"diesel": 2.3, "benzin": 2.0}})
        self.assertEqual([e["date"] for e in h["entries"]], ["2026-01-01", "2026-01-02"])
        self.assertTrue(h["entries"][1]["geo"])

    def test_begrenzung(self):
        h = {"entries": [{"date": f"2025-{m:02d}-{d:02d}"} for m in range(1, 13) for d in (1, 15)]}
        scrape.update_history(h, "2026-01-01", {}, keep=5)
        self.assertEqual(len(h["entries"]), 5)


if __name__ == "__main__":
    unittest.main()
