"""One-shot CLI for publishing the AI Office Dashboard V2 aggregate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .operations_dashboard_publication import (
    dashboard_publication_receipt_path,
    publish_operations_dashboard_bundle,
)
from .operations_dashboard_publisher import (
    dashboard_projection_path,
)
from .operations_dashboard_source import (
    build_live_operations_dashboard_projection,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description=(
            "Publish the bounded AI Office Dashboard V2 aggregate."
        )
    )
    value.add_argument("--state-root", required=True)
    value.add_argument(
        "--publisher-source-head",
        required=True,
    )
    value.add_argument(
        "--expected-operational-runtime-head",
        help=(
            "Expected Harness operational runtime identity for health binding. "
            "Defaults to --publisher-source-head."
        ),
    )
    value.add_argument("--output")
    value.add_argument("--receipt-output")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    state_root = Path(args.state_root).expanduser().resolve()
    if not state_root.is_dir() or state_root.is_symlink():
        raise SystemExit("state root unavailable")
    output = (
        Path(args.output).expanduser()
        if args.output
        else dashboard_projection_path(state_root)
    )
    receipt = (
        Path(args.receipt_output).expanduser()
        if args.receipt_output
        else dashboard_publication_receipt_path(output)
    )

    projection = build_live_operations_dashboard_projection(
        state_root,
        expected_operational_runtime_source=(
            args.expected_operational_runtime_head
            or args.publisher_source_head
        ),
    )
    projection_path, receipt_path = (
        publish_operations_dashboard_bundle(
            projection,
            output_path=output,
            receipt_path=receipt,
            publisher_source_head=args.publisher_source_head,
        )
    )
    print(
        json.dumps(
            {
                "schema_version": (
                    "orchestration.operations-dashboard-publish-result.v1"
                ),
                "projection_path": str(projection_path),
                "receipt_path": str(receipt_path),
                "projection_sha256": projection[
                    "projection_sha256"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
