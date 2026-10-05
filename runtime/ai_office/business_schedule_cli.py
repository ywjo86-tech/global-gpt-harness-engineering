"""Safe operator CLI for canonical AI Office business schedule state."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .business_schedule import (
    BUSINESS_SCHEDULE_ITEM_SCHEMA_V1,
    BUSINESS_SCHEDULE_REGISTRY_SCHEMA_V1,
    AIOfficeBusinessScheduleError,
    AIOfficeBusinessScheduleStore,
    BusinessScheduleItemV1,
    BusinessScheduleRegistryV1,
)


def parser() -> argparse.ArgumentParser:
    value=argparse.ArgumentParser(description="Manage canonical AI Office business schedule items.")
    value.add_argument("--state-root", required=True)
    commands=value.add_subparsers(dest="command", required=True)

    init=commands.add_parser("init")
    init.add_argument("--office-id", required=True)
    init.add_argument("--registry-ref", required=True)
    init.add_argument("--timezone-name", default="Asia/Seoul")

    put=commands.add_parser("put")
    put.add_argument("--item-id", required=True)
    put.add_argument("--title", required=True)
    put.add_argument("--start-at", required=True)
    put.add_argument("--status", required=True)
    put.add_argument("--source-ref", required=True)
    put.add_argument("--revision", required=True, type=int)

    commands.add_parser("validate")
    return value


def _state_root(raw: str) -> Path:
    root=Path(raw).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise AIOfficeBusinessScheduleError("state root unavailable")
    return root


def _summary(store: AIOfficeBusinessScheduleStore) -> dict[str, object]:
    registry=store.load_registry()
    items=store.load_items()
    return {
        "schema_version":"ai-office.business-schedule-cli-result.v1",
        "status":"PASS",
        "office_id":registry.office_id,
        "timezone_name":registry.timezone_name,
        "item_count":len(items),
        "scheduled_count":sum(1 for item in items if item.status=="SCHEDULED"),
        "active_count":sum(1 for item in items if item.status=="IN_PROGRESS"),
        "terminal_count":sum(1 for item in items if item.status in {"COMPLETED","CANCELLED"}),
        "blocked_count":sum(1 for item in items if item.status=="BLOCKED"),
        "registry_digest":registry.registry_digest,
    }


def main(argv: list[str] | None=None) -> int:
    args=parser().parse_args(argv)
    root=_state_root(args.state_root)
    store=AIOfficeBusinessScheduleStore(root)

    if args.command=="init":
        store.publish_registry(BusinessScheduleRegistryV1(
            BUSINESS_SCHEDULE_REGISTRY_SCHEMA_V1,
            args.office_id,
            args.timezone_name,
            args.registry_ref,
        ))
    elif args.command=="put":
        store.publish_item(BusinessScheduleItemV1(
            BUSINESS_SCHEDULE_ITEM_SCHEMA_V1,
            args.item_id,
            args.title,
            args.start_at,
            args.status,
            args.source_ref,
            args.revision,
        ))
    result=_summary(store)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
