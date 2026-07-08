"""Tests for the ClawCam field-summary mesh codec (pure, G2)."""

from clawcam_gateway.mesh.field_summary import (
    build_field_summary,
    decode_summary,
    encode_summary,
)


def _dets(*pairs):
    rows = []
    for subject, n in pairs:
        rows += [{"top_species": subject} for _ in range(n)]
    return rows


def test_build_counts_and_top_n():
    s = build_field_summary(
        "node-1", _dets(("deer", 20), ("fox", 12), ("turkey", 8), ("owl", 1)),
        ts=1_620_000_000, temperature_c=14.5, battery_percent=78, rssi=-92, top_n=3,
    )
    assert s["total"] == 41
    assert s["species"] == [("deer", 20), ("fox", 12), ("turkey", 8)]  # top 3, sorted
    assert s["temperature_c"] == 14.5


def test_encode_decode_round_trip():
    s = build_field_summary("node-1", _dets(("deer", 20), ("fox", 12)),
                            ts=1_620_000_000, temperature_c=14.5, battery_percent=78, rssi=-92)
    line = encode_summary(s)
    assert line.startswith("CC|dev=node-1|")
    back = decode_summary(line)
    assert back["device_id"] == "node-1"
    assert back["total"] == 32
    assert back["species"] == [("deer", 20), ("fox", 12)]
    assert back["ts"] == 1_620_000_000
    assert back["temperature_c"] == 14.5
    assert back["battery_percent"] == 78.0
    assert back["rssi"] == -92.0


def test_optional_fields_omitted():
    s = build_field_summary("n1", _dets(("deer", 3)))
    line = encode_summary(s)
    assert "tc=" not in line and "bat=" not in line and "rssi=" not in line and "ts=" not in line
    assert decode_summary(line)["total"] == 3


def test_size_bound_trims_species():
    # Many species → force the encoder to drop the tail to fit a tiny budget.
    many = _dets(*[(f"species{i:02d}", 20 - i) for i in range(15)])
    s = build_field_summary("node-1", many, top_n=15)
    line = encode_summary(s, max_bytes=80)
    assert len(line.encode("utf-8")) <= 80
    back = decode_summary(line)
    assert back["total"] == s["total"]              # count is never lost
    assert 0 < len(back["species"]) < 15            # some species dropped, not all
    # The species kept are the most frequent (head of the list).
    assert back["species"][0] == ("species00", 20)


def test_bad_magic_raises():
    import pytest
    with pytest.raises(ValueError):
        decode_summary("XX|dev=n1|det=1")


def test_int_temperature_stays_compact():
    s = build_field_summary("n1", _dets(("deer", 1)), temperature_c=15.0)
    line = encode_summary(s)
    assert "tc=15" in line and "tc=15.0" not in line
    assert decode_summary(line)["temperature_c"] == 15.0
