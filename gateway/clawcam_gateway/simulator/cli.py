"""CLI entrypoint for the ClawCam simulator.

Two modes:

* ``bundle`` (the default) — write a one-shot node-simulator payload bundle to a
  directory. This is the legacy behaviour: running with no subcommand still works
  (``python -m clawcam_gateway.simulator.cli --output DIR``).
* ``scenario`` — generate a deterministic multi-day detection stream and load it
  into a gateway SQLite database, so the analytics tools, REST endpoints, and
  dashboard show realistic historic data with no camera.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from clawcam_gateway.simulator.loader import load_stream_into_db
from clawcam_gateway.simulator.node_simulator import SimulatedNode
from clawcam_gateway.simulator.scenario import (
    ScenarioSpec,
    SpeciesProfile,
    build_detection_stream,
)


def _add_bundle_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--output", default="samples/node-simulator", help="Directory to write payloads into.")
    p.add_argument("--device-id", default="node-001", help="Simulated node ID.")
    p.add_argument("--deployment-id", default="deploy-north-ridge-2026", help="Deployment ID.")
    p.add_argument("--name", default="North Ridge Camera", help="Human-readable node name.")


def _run_bundle(args: argparse.Namespace) -> None:
    node = SimulatedNode(device_id=args.device_id, deployment_id=args.deployment_id, name=args.name)
    paths = node.write_bundle(args.output, datetime.now(timezone.utc))
    for payload_type, path in paths.items():
        print(f"{payload_type}: {path}")


def _parse_species(specs: list[str]) -> list[SpeciesProfile]:
    """Parse ``name[:rate[:diel[:label]]]`` species specs into profiles."""
    profiles: list[SpeciesProfile] = []
    for spec in specs:
        parts = spec.split(":")
        name = parts[0].strip()
        if not name:
            raise SystemExit(f"invalid --species (empty name): {spec!r}")
        rate = float(parts[1]) if len(parts) > 1 and parts[1] else 5.0
        diel = parts[2].strip() if len(parts) > 2 and parts[2] else "cathemeral"
        label = parts[3].strip() if len(parts) > 3 and parts[3] else "animal"
        profiles.append(SpeciesProfile(name=name, label=label, daily_rate=rate, diel=diel))
    return profiles


def _parse_days(csv: str | None) -> list[int]:
    if not csv:
        return []
    return [int(x) for x in csv.split(",") if x.strip() != ""]


def _run_scenario(args: argparse.Namespace) -> None:
    from clawcam_gateway.storage.database import GatewayDatabase

    species = _parse_species(args.species) if args.species else [
        SpeciesProfile("white-tailed deer", daily_rate=8, diel="crepuscular"),
        SpeciesProfile("red fox", daily_rate=4, diel="nocturnal"),
        SpeciesProfile("wild turkey", daily_rate=5, diel="diurnal"),
    ]
    spec = ScenarioSpec(
        species=species,
        days=args.days,
        start_date=args.start,
        device_id=args.device_id,
        deployment_id=args.deployment_id,
        seed=args.seed,
        spike_days=_parse_days(args.spike_days),
        drop_days=_parse_days(args.drop_days),
    )
    stream = build_detection_stream(spec)
    db = GatewayDatabase(args.db)
    counts = load_stream_into_db(
        db, stream,
        device_name=args.name,
        reviewed_frac=args.reviewed_frac,
        review_seed=args.seed,
    )
    print(
        f"loaded {counts['results']} detections across {counts['events']} events "
        f"for {counts['devices']} device(s) into {args.db} "
        f"({counts['reviewed']} reviewed)"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="ClawCam simulator.")
    # Legacy top-level (bundle) flags so `... cli --output DIR` keeps working.
    _add_bundle_args(parser)
    sub = parser.add_subparsers(dest="command")

    p_bundle = sub.add_parser("bundle", help="Write a one-shot node simulator payload bundle.")
    _add_bundle_args(p_bundle)

    p_scn = sub.add_parser("scenario", help="Generate a multi-day detection stream into a DB.")
    p_scn.add_argument("--db", required=True, help="Path to the gateway SQLite database to load into.")
    p_scn.add_argument("--days", type=int, default=14, help="Number of days to generate.")
    p_scn.add_argument("--start", default="2026-05-01", help="First day (UTC), YYYY-MM-DD.")
    p_scn.add_argument("--device-id", default="node-001", help="Simulated node ID.")
    p_scn.add_argument("--deployment-id", default="deploy-north-ridge-2026", help="Deployment ID.")
    p_scn.add_argument("--name", default="Scenario Simulator", help="Device display name.")
    p_scn.add_argument("--seed", type=int, default=0, help="Deterministic seed.")
    p_scn.add_argument(
        "--species", action="append", metavar="NAME[:RATE[:DIEL[:LABEL]]]",
        help="Species spec, repeatable (e.g. 'red fox:4:nocturnal'). Omit for a default set.",
    )
    p_scn.add_argument("--spike-days", help="Comma-separated 0-based day indices to spike (~5x).")
    p_scn.add_argument("--drop-days", help="Comma-separated 0-based day indices to drop to zero.")
    p_scn.add_argument(
        "--reviewed-frac", type=float, default=0.0, dest="reviewed_frac",
        help="Fraction (0..1) of rows to label with review states for calibration demos.",
    )

    args = parser.parse_args(argv)
    if args.command == "scenario":
        _run_scenario(args)
    else:  # None (legacy) or "bundle"
        _run_bundle(args)


if __name__ == "__main__":
    main()
