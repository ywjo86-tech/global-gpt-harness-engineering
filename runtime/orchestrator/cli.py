from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contract_loader import ContractLoadError
from .engine import OrchestrationEngine


def _print(obj: object) -> None:
    if isinstance(obj, (dict, list)):
        print(json.dumps(obj, indent=2, ensure_ascii=False))
    else:
        print(obj)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Global GPT Harness orchestration runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ["inspect", "plan", "run", "collect", "fanin", "approve", "gate", "status"]:
        sub = subparsers.add_parser(name)
        sub.add_argument("--project", required=True)
        if name in {"plan", "run", "gate"}:
            sub.add_argument("--mode", default="mock")
        if name in {"plan", "collect", "fanin", "gate", "status", "run"}:
            sub.add_argument("--run-id")
        if name == "approve":
            sub.add_argument("--approval", required=True)

    args = parser.parse_args(argv)
    engine = OrchestrationEngine(Path(args.project))

    try:
        if args.command == "inspect":
            _print(engine.inspect())
            return 0
        if args.command == "plan":
            _print(engine.plan(mode=args.mode, run_id=args.run_id))
            return 0
        if args.command == "run":
            _print(engine.run(mode=args.mode, run_id=args.run_id))
            return 0
        if args.command == "collect":
            _print(engine.collect(args.run_id))
            return 0
        if args.command == "fanin":
            _print(engine.fanin(args.run_id))
            return 0
        if args.command == "approve":
            _print(engine.approve(args.approval))
            return 0
        if args.command == "gate":
            _print(engine.gate(mode=args.mode, run_id=args.run_id))
            return 0
        if args.command == "status":
            _print(engine.status(args.run_id))
            return 0
    except ContractLoadError as exc:
        _print({"error": str(exc), "missing_files": exc.missing_files})
        return 2
    except PermissionError as exc:
        _print({"error": str(exc)})
        return 3

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
