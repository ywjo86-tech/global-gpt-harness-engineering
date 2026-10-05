from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from runtime.orchestrator.operations_current_attention import (
    build_current_attention_projection,
)
from runtime.orchestrator.operational_system_acceptance import (
    OperationalSystemAcceptanceError,
    build_operational_system_acceptance,
    load_operational_system_acceptance,
    operational_system_acceptance_path,
    record_operational_system_acceptance,
    validate_operational_system_acceptance,
)


def _gate(expected: str, *, status: str = "PASS", failures=()):
    return {
        "status": status,
        "failures": list(failures),
        "expected_runtime_source_identity": expected,
        "gate_evidence_sha256": "c" * 64,
    }




def _delivery(runtime: str, *, status: str = "PASS", observed_at: str = "2026-10-05T09:00:00+00:00"):
    import hashlib
    unsigned = {
        "schema_version": "orchestration.attention-delivery-health.v1",
        "observed_at": observed_at,
        "runtime_source_identity": runtime,
        "status": status,
        "current_eligible_count": 0,
        "historical_unresolved_count": 0,
        "delivered_count": 0,
        "error_count": 0,
        "errors": [],
        "control_authority": "NONE",
    }
    raw = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return {**unsigned, "health_sha256": hashlib.sha256(raw).hexdigest()}

def test_system_acceptance_accepts_only_current_bound_healthy_runtime(tmp_path):
    now = "2026-10-05T09:00:00+00:00"
    expected = "runtime:new"
    attention = build_current_attention_projection(
        runtime_source_identity=expected,
        blockers=[],
        observed_at=datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc),
    )

    record = build_operational_system_acceptance(
        runtime_source_identity=expected,
        expected_runtime_source_identity=expected,
        registered_project_count=9,
        post_change_gate=_gate(expected),
        current_attention_projection=attention,
        attention_delivery_health=_delivery(expected),
        monitor_health_receipt_refs=("attention.json", "reconcile.json"),
        process_lifecycle_diagnostic_refs=("process.json",),
        created_at=now,
    )

    assert record.status == "ACCEPTED"
    assert record.blocking_project_count == 0
    assert record.blocking_reasons == ()
    validate_operational_system_acceptance(record.to_dict())

    path = record_operational_system_acceptance(tmp_path, record)
    assert path == operational_system_acceptance_path(tmp_path)
    loaded = load_operational_system_acceptance(tmp_path)
    assert loaded.record_sha256 == record.record_sha256
    history = tmp_path / "_workspace" / "operational-system-acceptance"
    assert (history / f"{record.record_sha256}.json").is_file()


def test_system_acceptance_blocks_runtime_mismatch():
    attention = build_current_attention_projection(
        runtime_source_identity="runtime:old",
        blockers=[],
    )
    record = build_operational_system_acceptance(
        runtime_source_identity="runtime:old",
        expected_runtime_source_identity="runtime:new",
        registered_project_count=1,
        post_change_gate=_gate("runtime:new"),
        current_attention_projection=attention,
        attention_delivery_health=_delivery("runtime:old", observed_at=datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    assert record.status == "BLOCKED"
    assert "RUNTIME_SOURCE_MISMATCH" in record.blocking_reasons
    assert "ATTENTION_RUNTIME_SOURCE_MISMATCH" in record.blocking_reasons


def test_system_acceptance_blocks_current_operational_blocker():
    expected = "runtime:new"
    attention = build_current_attention_projection(
        runtime_source_identity=expected,
        blockers=[{
            "project_id": "P",
            "run_id": "R",
            "state": "BLOCKED",
            "kind": "DEAD_LETTER",
            "reason": "retry budget exhausted",
        }],
    )
    record = build_operational_system_acceptance(
        runtime_source_identity=expected,
        expected_runtime_source_identity=expected,
        registered_project_count=1,
        post_change_gate=_gate(expected, status="BLOCKED", failures=("ATTENTION_HEALTH:MONITOR_RECEIPT_BLOCKED",)),
        current_attention_projection=attention,
        attention_delivery_health=_delivery(expected),
        created_at="2026-10-05T09:00:00+00:00",
    )
    assert record.status == "BLOCKED"
    assert record.blocking_project_count == 1
    assert "CURRENT_OPERATIONAL_BLOCKERS:1" in record.blocking_reasons
    assert any(x.startswith("POST_CHANGE:") for x in record.blocking_reasons)


def test_system_acceptance_rejects_tamper():
    expected = "runtime:new"
    attention = build_current_attention_projection(
        runtime_source_identity=expected,
        blockers=[],
    )
    record = build_operational_system_acceptance(
        runtime_source_identity=expected,
        expected_runtime_source_identity=expected,
        registered_project_count=1,
        post_change_gate=_gate(expected),
        current_attention_projection=attention,
        attention_delivery_health=_delivery(expected),
        created_at="2026-10-05T09:00:00+00:00",
    )
    value = record.to_dict()
    value["runtime_source_identity"] = "runtime:tampered"
    with pytest.raises(OperationalSystemAcceptanceError):
        validate_operational_system_acceptance(value)


def test_system_acceptance_rejects_accepted_record_with_blockers():
    expected = "runtime:new"
    attention = build_current_attention_projection(
        runtime_source_identity=expected,
        blockers=[],
    )
    record = build_operational_system_acceptance(
        runtime_source_identity=expected,
        expected_runtime_source_identity=expected,
        registered_project_count=1,
        post_change_gate=_gate(expected),
        current_attention_projection=attention,
        attention_delivery_health=_delivery(expected),
        created_at="2026-10-05T09:00:00+00:00",
    )
    value = record.to_dict()
    value["blocking_project_count"] = 1
    unsigned = dict(value)
    unsigned.pop("record_sha256")
    import hashlib
    raw = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    value["record_sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(OperationalSystemAcceptanceError):
        validate_operational_system_acceptance(value)


def test_system_acceptance_blocks_missing_delivery_health():
    expected = "runtime:new"
    attention = build_current_attention_projection(
        runtime_source_identity=expected, blockers=[],
        observed_at=datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc),
    )
    record = build_operational_system_acceptance(
        runtime_source_identity=expected, expected_runtime_source_identity=expected,
        registered_project_count=1, post_change_gate=_gate(expected),
        current_attention_projection=attention, attention_delivery_health=None,
        created_at="2026-10-05T09:00:00+00:00",
    )
    assert record.status == "BLOCKED"
    assert "ATTENTION_DELIVERY:UNAVAILABLE" in record.blocking_reasons


def test_system_acceptance_blocks_unconfigured_and_stale_delivery():
    expected = "runtime:new"
    attention = build_current_attention_projection(
        runtime_source_identity=expected, blockers=[],
        observed_at=datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc),
    )
    record = build_operational_system_acceptance(
        runtime_source_identity=expected, expected_runtime_source_identity=expected,
        registered_project_count=1, post_change_gate=_gate(expected),
        current_attention_projection=attention,
        attention_delivery_health=_delivery(expected, status="ATTENTION_DELIVERY_UNCONFIGURED", observed_at="2026-10-05T08:00:00+00:00"),
        created_at="2026-10-05T09:00:00+00:00", delivery_stale_after_seconds=180,
    )
    assert record.status == "BLOCKED"
    assert "ATTENTION_DELIVERY:ATTENTION_DELIVERY_UNCONFIGURED" in record.blocking_reasons
    assert "ATTENTION_DELIVERY:STALE" in record.blocking_reasons
