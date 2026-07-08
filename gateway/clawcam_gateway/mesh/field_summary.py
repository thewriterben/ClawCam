"""Compact field-summary codec for the ClawCam↔OBC mesh bridge (G2).

A LoRa frame carries only ~200 usable bytes, so a camera on the mesh can't ship
detections or images — it ships a *summary*: how many detections, of the top few species,
plus the latest conditions and node health. This module builds that summary from already
-fetched data and encodes it to a compact, self-describing, **size-bounded** line that a
base station parses back out. When the payload would overflow the byte budget, the least
important content (the tail of the species list) is dropped until it fits.

Pure and storage-agnostic: no DB or framework imports.

Wire format (pipe-delimited ``key=value``, magic ``CC`` first)::

    CC|dev=node-1|ts=1620000000|det=42|sp=deer:20,fox:12|tc=14.5|bat=78|rssi=-92

Only ``dev`` and ``det`` are guaranteed present; optional fields are omitted when unknown.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

MAGIC = "CC"
DEFAULT_MAX_BYTES = 200


def _subject(det: dict[str, Any]) -> str | None:
    return det.get("top_species") or det.get("top_label")


def build_field_summary(
    device_id: str,
    detections: list[dict[str, Any]],
    ts: int | None = None,
    temperature_c: float | None = None,
    battery_percent: float | None = None,
    rssi: float | None = None,
    top_n: int = 5,
) -> dict[str, Any]:
    """Roll a detection batch + node status into a compact summary dict.

    ``species`` is the ``top_n`` most-frequent subjects as ``[(name, count), …]`` (most
    frequent first). Missing optional fields are left as ``None``.
    """
    counts: Counter[str] = Counter()
    for d in detections:
        s = _subject(d)
        if s:
            counts[s] += 1
    return {
        "device_id": device_id,
        "ts": ts,
        "total": sum(counts.values()),
        "species": counts.most_common(max(0, int(top_n))),
        "temperature_c": temperature_c,
        "battery_percent": battery_percent,
        "rssi": rssi,
    }


def _fmt_num(x: float) -> str:
    """Compact number: drop a trailing ``.0`` so ints stay short."""
    return str(int(x)) if float(x).is_integer() else str(round(float(x), 1))


def encode_summary(summary: dict[str, Any], max_bytes: int = DEFAULT_MAX_BYTES) -> str:
    """Encode a summary to a size-bounded wire line.

    Guarantees the UTF-8 length is ``<= max_bytes`` by trimming the tail of the species
    list (dropping ``sp`` entirely if needed). ``dev`` and ``det`` always survive.
    """
    head = [MAGIC, f"dev={summary['device_id']}"]
    if summary.get("ts") is not None:
        head.append(f"ts={int(summary['ts'])}")
    head.append(f"det={int(summary.get('total', 0))}")

    tail: list[str] = []
    for key, val in (
        ("tc", summary.get("temperature_c")),
        ("bat", summary.get("battery_percent")),
        ("rssi", summary.get("rssi")),
    ):
        if val is not None:
            tail.append(f"{key}={_fmt_num(val)}")

    species = list(summary.get("species") or [])

    def assemble(n_species: int) -> str:
        parts = list(head)
        if n_species > 0 and species:
            sp = ",".join(f"{name}:{cnt}" for name, cnt in species[:n_species])
            parts.append(f"sp={sp}")
        parts.extend(tail)
        return "|".join(parts)

    # Try the full species list, then shrink until it fits the byte budget.
    for n in range(len(species), -1, -1):
        line = assemble(n)
        if len(line.encode("utf-8")) <= max_bytes:
            return line
    return assemble(0)  # minimal (head+tail); may exceed only in pathological device ids


def decode_summary(line: str) -> dict[str, Any]:
    """Parse a wire line back into a summary dict (inverse of :func:`encode_summary`).

    Raises ``ValueError`` if the magic prefix is missing.
    """
    parts = line.strip().split("|")
    if not parts or parts[0] != MAGIC:
        raise ValueError("not a ClawCam field summary (missing 'CC' magic)")
    out: dict[str, Any] = {
        "device_id": None, "ts": None, "total": 0, "species": [],
        "temperature_c": None, "battery_percent": None, "rssi": None,
    }
    for kv in parts[1:]:
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        if k == "dev":
            out["device_id"] = v
        elif k == "ts":
            out["ts"] = int(v)
        elif k == "det":
            out["total"] = int(v)
        elif k == "sp":
            pairs = []
            for item in v.split(","):
                if ":" in item:
                    name, cnt = item.rsplit(":", 1)
                    pairs.append((name, int(cnt)))
            out["species"] = pairs
        elif k == "tc":
            out["temperature_c"] = float(v)
        elif k == "bat":
            out["battery_percent"] = float(v)
        elif k == "rssi":
            out["rssi"] = float(v)
    return out
