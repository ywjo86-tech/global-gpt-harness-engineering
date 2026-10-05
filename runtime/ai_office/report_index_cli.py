"""Safe operator CLI for canonical AI Office report indexing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .report_index import (
    OFFICE_REPORT_INDEX_REGISTRY_SCHEMA_V1,
    AIOfficeReportIndexError,
    AIOfficeReportIndexStore,
    OfficeReportIndexRegistryV1,
    office_report_from_mapping,
)


def parser() -> argparse.ArgumentParser:
    value=argparse.ArgumentParser(description="Manage canonical AI Office OfficeReportV1 index.")
    value.add_argument("--state-root", required=True)
    commands=value.add_subparsers(dest="command", required=True)

    init=commands.add_parser("init")
    init.add_argument("--office-id", required=True)
    init.add_argument("--registry-ref", required=True)

    add=commands.add_parser("add")
    add.add_argument("--report-id", required=True)
    add.add_argument("--title", required=True)
    add.add_argument("--published-at", required=True)
    add.add_argument("--report-file", required=True)
    add.add_argument("--report-ref", required=True)

    commands.add_parser("validate")
    return value


def _state_root(raw: str) -> Path:
    root=Path(raw).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise AIOfficeReportIndexError("state root unavailable")
    return root


def _load_source_report(raw: str):
    path=Path(raw).expanduser()
    if path.is_symlink() or not path.is_file():
        raise AIOfficeReportIndexError("report source unavailable or unsafe")
    try:
        value=json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AIOfficeReportIndexError("report source unreadable") from exc
    return office_report_from_mapping(value)


def _summary(store: AIOfficeReportIndexStore) -> dict[str, object]:
    registry=store.load_registry()
    entries=store.load_entries()
    return {
        "schema_version":"ai-office.report-index-cli-result.v1",
        "status":"PASS",
        "office_id":registry.office_id,
        "report_count":len(entries),
        "registry_digest":registry.registry_digest,
    }


def main(argv: list[str] | None=None) -> int:
    args=parser().parse_args(argv)
    root=_state_root(args.state_root)
    store=AIOfficeReportIndexStore(root)

    if args.command=="init":
        store.publish_registry(OfficeReportIndexRegistryV1(
            OFFICE_REPORT_INDEX_REGISTRY_SCHEMA_V1,
            args.office_id,
            args.registry_ref,
        ))
    elif args.command=="add":
        report=_load_source_report(args.report_file)
        store.publish_report(
            report_id=args.report_id,
            title=args.title,
            published_at=args.published_at,
            report=report,
            report_ref=args.report_ref,
        )
    result=_summary(store)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
