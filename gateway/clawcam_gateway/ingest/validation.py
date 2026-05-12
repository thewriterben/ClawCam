"""Schema validation helpers for ClawCam gateway ingest."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
import json

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - dependency message is explicit at runtime
    Draft202012Validator = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = REPO_ROOT / "schemas"


@lru_cache(maxsize=8)
def load_schema(schema_name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / schema_name
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_payload(payload: dict[str, Any], schema_name: str) -> None:
    """Validate a payload against a repository schema.

    Raises:
        RuntimeError: if jsonschema is not installed.
        jsonschema.ValidationError: if the payload does not satisfy the schema.
    """

    if Draft202012Validator is None:
        raise RuntimeError("jsonschema is required for ClawCam gateway validation")
    validator = Draft202012Validator(load_schema(schema_name))
    validator.validate(payload)


def validate_device(payload: dict[str, Any]) -> None:
    validate_payload(payload, "clawcam-device.schema.json")


def validate_event(payload: dict[str, Any]) -> None:
    validate_payload(payload, "clawcam-event.schema.json")


def validate_health(payload: dict[str, Any]) -> None:
    validate_payload(payload, "clawcam-health.schema.json")
