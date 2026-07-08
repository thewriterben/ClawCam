"""Mesh transport helpers for ClawCam (Conservation Grid G2).

Lets a camera with no IP backhaul report low-bandwidth field summaries over the
Oh-Ben-Claw LoRa spine. The codec here produces a compact, size-bounded payload
that fits a LoRa frame; a store-and-forward buffer (the existing ``cloud_uploads``
queue) and the transport itself are wired separately.
"""

from clawcam_gateway.mesh.field_summary import (
    build_field_summary,
    decode_summary,
    encode_summary,
)

__all__ = ["build_field_summary", "decode_summary", "encode_summary"]
