"""
Kantonszuordnung per Koordinate (Point-in-Polygon) gegen data/cantons.topo.json.

Ersetzt die frühere PLZ-Tabelle, die Kantonsgrenzen nicht abbilden kann
(Genf fehlte, Oberwallis, Appenzell, Ausserschwyz u.a. waren falsch zugeteilt).
Reine Standardbibliothek, keine Abhängigkeiten.
"""

import json
import math
from pathlib import Path

TOPO_PATH = Path(__file__).parent.parent / "data" / "cantons.topo.json"

# Stationen, die knapp ausserhalb der (vereinfachten) Grenzlinie liegen, werden dem
# nächsten Kanton zugeschlagen, wenn sie höchstens so weit entfernt sind (Grad, ≈ 400 m).
SNAP_DISTANCE_DEG = 0.004


def _decode_arcs(topo: dict) -> list[list[tuple[float, float]]]:
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    return arcs


def _ring(arc_ids: list[int], arcs: list) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in arc_ids:
        seg = arcs[i] if i >= 0 else arcs[~i][::-1]
        pts.extend(seg if not pts else seg[1:])
    return pts


def load_cantons(path: Path = TOPO_PATH) -> dict[str, list[list[list[tuple[float, float]]]]]:
    """Gibt {kürzel: [polygon, …]} zurück; polygon = [aussenring, loch, …] aus (lon, lat)."""
    topo = json.loads(Path(path).read_text())
    arcs = _decode_arcs(topo)
    out: dict = {}
    for g in topo["objects"]["cantons"]["geometries"]:
        polys = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"]
        out[g["id"]] = [[_ring(r, arcs) for r in poly] for poly in polys]
    return out


def _in_ring(lon: float, lat: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _dist_to_ring(lon: float, lat: float, ring: list[tuple[float, float]]) -> float:
    """Kleinster Abstand (Grad, Längengrad mit cos(lat) skaliert) zu den Segmenten."""
    k = math.cos(math.radians(lat))
    best = math.inf
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        ax, ay, bx, by = (x1 - lon) * k, y1 - lat, (x2 - lon) * k, y2 - lat
        dx, dy = bx - ax, by - ay
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


class CantonLocator:
    def __init__(self, cantons: dict | None = None):
        self.cantons = cantons or load_cantons()
        # Bounding-Boxen für schnellen Vorfilter
        self._bbox = {}
        for kz, polys in self.cantons.items():
            xs = [p[0] for poly in polys for p in poly[0]]
            ys = [p[1] for poly in polys for p in poly[0]]
            self._bbox[kz] = (min(xs), min(ys), max(xs), max(ys))

    def locate(self, lat: float, lon: float) -> str | None:
        for kz, polys in self.cantons.items():
            x0, y0, x1, y1 = self._bbox[kz]
            if not (x0 <= lon <= x1 and y0 <= lat <= y1):
                continue
            for poly in polys:
                if _in_ring(lon, lat, poly[0]) and not any(_in_ring(lon, lat, h) for h in poly[1:]):
                    return kz
        # knapp daneben (Vereinfachung der Grenzlinie)? → nächster Kanton
        best_kz, best_d = None, SNAP_DISTANCE_DEG
        for kz, polys in self.cantons.items():
            x0, y0, x1, y1 = self._bbox[kz]
            if not (x0 - SNAP_DISTANCE_DEG <= lon <= x1 + SNAP_DISTANCE_DEG
                    and y0 - SNAP_DISTANCE_DEG <= lat <= y1 + SNAP_DISTANCE_DEG):
                continue
            for poly in polys:
                d = _dist_to_ring(lon, lat, poly[0])
                if d < best_d:
                    best_kz, best_d = kz, d
        return best_kz
