"""Bound publication receipt for the AI Office Dashboard V2 aggregate."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .durable_io import DurableIOError, atomic_write_json
from .operations_dashboard_projection import (
    DASHBOARD_SOURCE_CONTRACT_V2,
    OperationsDashboardProjectionError,
    validate_operations_dashboard_projection,
)
from .operations_dashboard_publisher import (
    OperationsDashboardPublisherError,
    publish_operations_dashboard_projection,
)

DASHBOARD_PUBLICATION_RECEIPT_SCHEMA_V1 = (
    "orchestration.operations-dashboard-publication-receipt.v1"
)
DASHBOARD_PUBLISHER_COMPONENT = "OPERATIONS_DASHBOARD_PUBLISHER"
_HEAD = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class OperationsDashboardPublicationError(ValueError):
    pass


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def publication_receipt_digest(value: Mapping[str, Any]) -> str:
    unsigned = {
        key: child for key, child in value.items()
        if key != "receipt_sha256"
    }
    return hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise OperationsDashboardPublicationError(f"{label} missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OperationsDashboardPublicationError(f"{label} invalid") from exc
    if parsed.tzinfo is None:
        raise OperationsDashboardPublicationError(
            f"{label} must be timezone-aware"
        )
    return parsed.astimezone(timezone.utc)


def dashboard_publication_receipt_path(
    projection_path: str | Path,
) -> Path:
    projection = Path(projection_path).expanduser()
    return projection.with_name(projection.name + ".receipt.json")


def build_dashboard_publication_receipt(
    projection: Mapping[str, Any],
    *,
    publisher_source_head: str,
    published_at: datetime | None = None,
) -> dict[str, Any]:
    try:
        value = validate_operations_dashboard_projection(projection)
    except OperationsDashboardProjectionError as exc:
        raise OperationsDashboardPublicationError(str(exc)) from exc

    head = str(publisher_source_head or "").strip()
    if not _HEAD.fullmatch(head):
        raise OperationsDashboardPublicationError(
            "publisher source HEAD invalid"
        )

    current = (
        published_at or datetime.now(timezone.utc)
    ).astimezone(timezone.utc)
    receipt: dict[str, Any] = {
        "schema_version": DASHBOARD_PUBLICATION_RECEIPT_SCHEMA_V1,
        "source_contract": DASHBOARD_SOURCE_CONTRACT_V2,
        "projection_sha256": value["projection_sha256"],
        "published_at": current.isoformat(),
        "publisher_component": DASHBOARD_PUBLISHER_COMPONENT,
        "publisher_source_head": head,
    }
    receipt["receipt_sha256"] = publication_receipt_digest(receipt)
    return validate_dashboard_publication_receipt(
        receipt,
        projection=value,
    )


def validate_dashboard_publication_receipt(
    receipt: Mapping[str, Any],
    *,
    projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        raise OperationsDashboardPublicationError(
            "publication receipt mapping required"
        )
    value = dict(receipt)
    expected = {
        "schema_version",
        "source_contract",
        "projection_sha256",
        "published_at",
        "publisher_component",
        "publisher_source_head",
        "receipt_sha256",
    }
    if set(value) != expected:
        raise OperationsDashboardPublicationError(
            "publication receipt shape mismatch"
        )
    if (
        value["schema_version"]
        != DASHBOARD_PUBLICATION_RECEIPT_SCHEMA_V1
    ):
        raise OperationsDashboardPublicationError(
            "publication receipt schema mismatch"
        )
    if value["source_contract"] != DASHBOARD_SOURCE_CONTRACT_V2:
        raise OperationsDashboardPublicationError(
            "publication source contract mismatch"
        )
    if value["publisher_component"] != DASHBOARD_PUBLISHER_COMPONENT:
        raise OperationsDashboardPublicationError(
            "publication publisher mismatch"
        )
    head = str(value["publisher_source_head"])
    if not _HEAD.fullmatch(head):
        raise OperationsDashboardPublicationError(
            "publisher source HEAD invalid"
        )
    _timestamp(value["published_at"], "published_at")
    projection_digest = str(value["projection_sha256"])
    if (
        len(projection_digest) != 64
        or any(
            ch not in "0123456789abcdef"
            for ch in projection_digest
        )
    ):
        raise OperationsDashboardPublicationError(
            "projection digest invalid"
        )
    if (
        str(value["receipt_sha256"])
        != publication_receipt_digest(value)
    ):
        raise OperationsDashboardPublicationError(
            "publication receipt digest mismatch"
        )
    if projection is not None:
        try:
            projection_value = (
                validate_operations_dashboard_projection(projection)
            )
        except OperationsDashboardProjectionError as exc:
            raise OperationsDashboardPublicationError(
                str(exc)
            ) from exc
        if (
            projection_value["projection_sha256"]
            != projection_digest
        ):
            raise OperationsDashboardPublicationError(
                "projection/receipt binding mismatch"
            )
    return value


def publish_operations_dashboard_bundle(
    projection: Mapping[str, Any],
    *,
    output_path: str | Path,
    publisher_source_head: str,
    receipt_path: str | Path | None = None,
    published_at: datetime | None = None,
) -> tuple[Path, Path]:
    target = Path(output_path).expanduser()
    receipt_target = (
        Path(receipt_path).expanduser()
        if receipt_path is not None
        else dashboard_publication_receipt_path(target)
    )
    if (
        receipt_target.exists()
        and receipt_target.is_symlink()
    ):
        raise OperationsDashboardPublicationError(
            "refusing symlink dashboard receipt"
        )
    receipt = build_dashboard_publication_receipt(
        projection,
        publisher_source_head=publisher_source_head,
        published_at=published_at,
    )
    try:
        projection_written = (
            publish_operations_dashboard_projection(
                projection,
                output_path=target,
            )
        )
    except OperationsDashboardPublisherError as exc:
        raise OperationsDashboardPublicationError(
            str(exc)
        ) from exc
    try:
        receipt_written = atomic_write_json(
            receipt_target,
            receipt,
        )
    except (DurableIOError, OSError) as exc:
        raise OperationsDashboardPublicationError(
            "dashboard publication receipt write failed"
        ) from exc
    return projection_written, receipt_written
