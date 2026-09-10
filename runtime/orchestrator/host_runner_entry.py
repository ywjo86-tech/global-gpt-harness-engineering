"""Foreground HOST_GATEWAY runner entrypoint.

This is intentionally one-shot: deployment supervisors may invoke it per
request or wrap it later, but the harness never starts a background daemon.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .production_execution_gateway import UnixSocketHostRunner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one authenticated HOST_GATEWAY request in the foreground")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)
    # Production has one path: App Server dynamic tools -> Gateway -> Broker.
    # The legacy CLI executor remains only as an explicit injected test seam.
    runner = UnixSocketHostRunner(Path(args.socket), Path(args.ledger), broker_native=True)
    runner.serve_once(timeout=args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
