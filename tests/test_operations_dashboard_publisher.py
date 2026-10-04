from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from runtime.orchestrator.operations_dashboard_projection import (
    build_operations_dashboard_projection,
)
from runtime.orchestrator.operations_dashboard_publisher import (
    OperationsDashboardPublisherError,
    publish_operations_dashboard_projection,
)


def _projection():
    return build_operations_dashboard_projection(
        [],
        system_health={
            "attention": "PASS",
            "reconcile": "PASS",
            "post_change": "PASS",
            "acceptance": "ACCEPTED",
        },
        system_resources={
            "cpu_percent": 10,
            "memory_percent": 20,
            "storage_percent": 30,
            "source": "fixture",
        },
        now=datetime(2026, 10, 4, 5, tzinfo=timezone.utc),
    )


def test_publisher_writes_verified_projection_atomically(tmp_path):
    output = tmp_path / "operations-v2" / "ai-office-dashboard-v2.json"
    value = _projection()

    result = publish_operations_dashboard_projection(value, output_path=output)

    assert result == output
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded == value
    assert not list(output.parent.glob(output.name + ".*"))


def test_publisher_rejects_symlink_output(tmp_path):
    target = tmp_path / "real.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "dashboard.json"
    link.symlink_to(target)

    with pytest.raises(OperationsDashboardPublisherError, match="symlink"):
        publish_operations_dashboard_projection(_projection(), output_path=link)


def test_publisher_rejects_tampered_projection(tmp_path):
    value = _projection()
    value["summary"]["issues"] = 7

    with pytest.raises(OperationsDashboardPublisherError, match="digest mismatch"):
        publish_operations_dashboard_projection(
            value,
            output_path=tmp_path / "dashboard.json",
        )
