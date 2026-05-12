#!/usr/bin/env python3
"""Validate core ClawCam repository contracts."""

from __future__ import annotations

from pathlib import Path
import json

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"


def validate_schemas() -> None:
    for schema_path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        print(f"ok schema {schema_path.relative_to(ROOT)}")


def main() -> None:
    validate_schemas()


if __name__ == "__main__":
    main()
