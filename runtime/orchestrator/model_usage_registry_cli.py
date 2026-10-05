"""Operator CLI for the canonical model-usage instrumentation registry."""
from __future__ import annotations

import argparse
import json

from .operations_dashboard_model_usage import (
    initialize_model_usage_registry,
    read_model_usage_registry,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Manage model usage registry.")
    value.add_argument("--state-root", required=True)
    commands = value.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--activated-at", required=True)
    init.add_argument("--registry-ref", required=True)
    commands.add_parser("validate")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "init":
        initialize_model_usage_registry(
            args.state_root,
            activated_at=args.activated_at,
            registry_ref=args.registry_ref,
        )
    registry = read_model_usage_registry(args.state_root)
    print(json.dumps({
        "schema_version": "orchestration.model-usage-registry-cli-result.v1",
        "status": "PASS",
        "activated_at": registry["activated_at"],
        "registry_digest": registry["registry_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
