"""Atomic publisher for the AI Office Dashboard V2 aggregate."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .durable_io import DurableIOError, atomic_write_json
from .operations_dashboard_projection import (
    OperationsDashboardProjectionError,
    validate_operations_dashboard_projection,
)


class OperationsDashboardPublisherError(ValueError):
    pass


def dashboard_projection_path(state_root: str | Path) -> Path:
    root = Path(state_root).expanduser().resolve()
    return root / "operations-v2" / "ai-office-dashboard-v2.json"


def publish_operations_dashboard_projection(
    projection: Mapping[str, Any],
    *,
    output_path: str | Path,
) -> Path:
    target = Path(output_path).expanduser()
    if target.exists() and target.is_symlink():
        raise OperationsDashboardPublisherError("refusing symlink dashboard output")
    try:
        value = validate_operations_dashboard_projection(projection)
    except OperationsDashboardProjectionError as exc:
        raise OperationsDashboardPublisherError(str(exc)) from exc
    try:
        return atomic_write_json(target, value)
    except (DurableIOError, OSError) as exc:
        raise OperationsDashboardPublisherError("dashboard projection publish failed") from exc
