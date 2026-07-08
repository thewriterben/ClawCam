"""Habitat use vs availability — do detections prefer a land-cover class? (G7)

Satellite imagery (Sentinel/Landsat) is only useful to conservation once it's *classified*
into land cover and overlaid on the survey area. This builder is the analysis that overlay
enables: given a land-cover raster and geo-tagged detections, it compares how much each
habitat class is **used** (share of detections there) against how much is **available**
(share of the area), and reports the ecologist's standard selection signals —
``selection_ratio`` (used ÷ available; >1 = preferred, <1 = avoided) and Ivlev
``electivity`` ((u−a)/(u+a) ∈ [−1, 1]).

Pure and storage-agnostic: takes a ``LandCover`` grid and detection dicts carrying a
location; no DB, no imagery fetch (the raster is supplied — in production from a Sentinel
classification clipped to the site).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass
class LandCover:
    """A land-cover classification on a regular lat/lon grid.

    ``rows[r][c]`` is the class label at ``(lat = origin_lat + r*step,
    lon = origin_lon + c*step)``. Class labels are arbitrary strings (e.g. ``"forest"``,
    ``"grassland"``, ``"water"``).
    """

    origin_lat: float
    origin_lon: float
    step: float
    rows: list[list[str]]

    def classify(self, lat: float, lon: float) -> str | None:
        """Nearest-cell class for a point, or ``None`` if outside the mapped grid."""
        if not self.rows or self.step <= 0:
            return None
        r = round((lat - self.origin_lat) / self.step)
        c = round((lon - self.origin_lon) / self.step)
        if 0 <= r < len(self.rows) and 0 <= c < len(self.rows[r]):
            return self.rows[r][c]
        return None

    def availability(self) -> Counter[str]:
        """Cell count per class — the available-area proxy."""
        cells: Counter[str] = Counter()
        for row in self.rows:
            for cls in row:
                cells[cls] += 1
        return cells


def _loc(det: dict[str, Any]) -> tuple[float, float] | None:
    loc = det.get("location") or {}
    lat = det.get("latitude", loc.get("latitude"))
    lon = det.get("longitude", loc.get("longitude"))
    if lat is None or lon is None:
        return None
    return float(lat), float(lon)


def _subject(det: dict[str, Any]) -> str | None:
    return det.get("top_species") or det.get("top_label")


def build_habitat_report(
    detections: list[dict[str, Any]],
    landcover: LandCover,
    top_n: int = 3,
) -> dict[str, Any]:
    """Compare detection use of each land-cover class against its availability.

    Args:
        detections: rows carrying a location (``latitude``/``longitude`` or a nested
                    ``location``) and ``top_species``/``top_label``.
        landcover:  the classified raster over the survey area.
        top_n:      how many top species to list per class.

    Returns ``total_cells``, ``located``/``unlocated`` detection counts, and a ``classes``
    list (most-used first) each with ``use``, ``use_fraction``, ``availability_cells``,
    ``availability_fraction``, ``selection_ratio``, ``electivity``, and ``top_species``.
    """
    avail = landcover.availability()
    total_cells = sum(avail.values())

    use: Counter[str] = Counter()
    species_by_class: dict[str, Counter[str]] = defaultdict(Counter)
    located = 0
    unlocated = 0
    for det in detections:
        pos = _loc(det)
        if pos is None:
            unlocated += 1
            continue
        cls = landcover.classify(*pos)
        if cls is None:
            unlocated += 1
            continue
        located += 1
        use[cls] += 1
        subj = _subject(det)
        if subj:
            species_by_class[cls][subj] += 1

    classes: list[dict[str, Any]] = []
    for cls, cells in avail.items():
        u = use.get(cls, 0)
        uf = u / located if located else 0.0
        af = cells / total_cells if total_cells else 0.0
        ratio = round(uf / af, 3) if af > 0 else None
        elect = round((uf - af) / (uf + af), 3) if (uf + af) > 0 else None
        classes.append({
            "class": cls,
            "use": u,
            "use_fraction": round(uf, 3),
            "availability_cells": cells,
            "availability_fraction": round(af, 3),
            "selection_ratio": ratio,
            "electivity": elect,
            "top_species": species_by_class[cls].most_common(max(0, int(top_n))),
        })
    classes.sort(key=lambda c: (-c["use"], c["class"]))

    return {
        "total_cells": total_cells,
        "located": located,
        "unlocated": unlocated,
        "classes": classes,
    }
