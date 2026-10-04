from __future__ import annotations

from datetime import datetime, timezone

import pytest

from runtime.orchestrator.operations_dashboard_projection import (
    DASHBOARD_SOURCE_CONTRACT_V2,
    InvalidCurrentWorkObservationV1,
    OperationsDashboardProjectionError,
    build_operations_dashboard_projection,
    validate_operations_dashboard_projection,
)
from runtime.orchestrator.operations_read_model import OperationsReadModelV1, SourceIdentityV1


def _model(
    project: str,
    run: str,
    state: str,
    timestamp: str,
    *,
    gate: str = "GATE-001",
    approval_required: bool = False,
    current_work: str = "",
) -> OperationsReadModelV1:
    return OperationsReadModelV1(
        schema_version="orchestration.operations-read-model.v1",
        project_id=project,
        run_id=run,
        task_id="TASK-001",
        gate_id=gate,
        raw_state=state,
        normalized_state=state,
        human_state=state,
        progress=None,
        progress_source="",
        current_work=current_work,
        outcome="",
        impact="",
        next_step="",
        approval_required=approval_required,
        approval_refs=(),
        checkpoint_refs=(),
        evidence_refs=(),
        sources=(
            SourceIdentityV1(
                source_component="TEST",
                source_version="v1",
                source_head="a" * 40,
                source_timestamp=timestamp,
            ),
        ),
        freshness="FRESH",
        diagnostic_health=None,
        operational_acceptance=None,
    )


def _green_health():
    return {
        "attention": "PASS",
        "reconcile": "PASS",
        "post_change": "PASS",
        "acceptance": "ACCEPTED",
    }


def test_retry_history_is_not_double_counted():
    result = build_operations_dashboard_projection(
        [
            _model("a", "retry-old", "STALLED", "2026-10-04T01:00:00+00:00"),
            _model("a", "success-new", "COMPLETED", "2026-10-04T02:00:00+00:00"),
            _model("b", "running", "RUNNING", "2026-10-04T03:00:00+00:00"),
        ],
        system_health=_green_health(),
        now=datetime(2026, 10, 4, 5, tzinfo=timezone.utc),
    )

    assert result["summary"]["total_work"] == 2
    assert result["summary"]["running"] == 1
    assert result["summary"]["issues"] == 0
    assert {row["run_id"] for row in result["recent_requests"]} == {"success-new", "running"}


def test_latest_invalid_observation_blocks_fallback_to_older_green():
    result = build_operations_dashboard_projection(
        [_model("a", "old-green", "COMPLETED", "2026-10-04T01:00:00+00:00")],
        invalid_current=(
            InvalidCurrentWorkObservationV1(
                project_id="a",
                run_id="new-corrupt",
                source_timestamp="2026-10-04T02:00:00+00:00",
                reason="digest mismatch",
                source_ref="/qualified/state.json",
            ),
        ),
        system_health=_green_health(),
        now=datetime(2026, 10, 4, 5, tzinfo=timezone.utc),
    )

    assert result["summary"]["total_work"] == 1
    assert result["summary"]["issues"] == 1
    assert result["data_quality"]["invalid_current_projects"] == 1
    assert result["recent_requests"][0]["run_id"] == "new-corrupt"
    assert result["recent_requests"][0]["state"] == "UNKNOWN"
    assert result["alerts"][0]["kind"] == "DATA_QUALITY"


def test_blocked_or_failed_current_work_is_visible():
    result = build_operations_dashboard_projection(
        [
            _model(
                "a",
                "failed",
                "FAILED",
                "2026-10-04T02:00:00+00:00",
                current_work="provider recovery failed",
            )
        ],
        system_health=_green_health(),
        now=datetime(2026, 10, 4, 5, tzinfo=timezone.utc),
    )

    assert result["summary"]["issues"] == 1
    assert result["alerts"][0]["kind"] == "PROJECT_STATE"
    assert "provider recovery failed" in result["alerts"][0]["detail"]


def test_operational_health_failure_is_visible():
    health = _green_health()
    health["reconcile"] = "BLOCKED"

    result = build_operations_dashboard_projection(
        [_model("a", "ok", "COMPLETED", "2026-10-04T02:00:00+00:00")],
        system_health=health,
        now=datetime(2026, 10, 4, 5, tzinfo=timezone.utc),
    )

    assert result["summary"]["issues"] == 1
    assert result["system_health"]["reconcile"] == "BLOCKED"
    assert any(item["kind"] == "SYSTEM_HEALTH" for item in result["alerts"])


def test_missing_department_schedule_report_sources_are_explicit():
    result = build_operations_dashboard_projection(
        [],
        system_health=_green_health(),
        now=datetime(2026, 10, 4, 5, tzinfo=timezone.utc),
    )

    assert all(row["binding_state"] == "UNBOUND" for row in result["departments"])
    assert all(row["progress"] is None for row in result["departments"])
    assert result["today_schedule"]["source_state"] == "UNAVAILABLE"
    assert result["today_schedule"]["items"] == []
    assert result["recent_reports"]["source_state"] == "UNAVAILABLE"
    assert result["recent_reports"]["items"] == []


def test_forbidden_provider_or_authority_field_is_rejected():
    with pytest.raises(OperationsDashboardProjectionError, match="forbidden dashboard field"):
        build_operations_dashboard_projection(
            [],
            system_health=_green_health(),
            jarvis_status={
                "webapp": "AVAILABLE",
                "memory": "AVAILABLE",
                "llmwiki": "AVAILABLE",
                "source_state": "CANONICAL",
                "provider": "must-not-leak",
            },
            now=datetime(2026, 10, 4, 5, tzinfo=timezone.utc),
        )


def test_projection_digest_detects_tamper():
    result = build_operations_dashboard_projection(
        [_model("a", "ok", "COMPLETED", "2026-10-04T02:00:00+00:00")],
        system_health=_green_health(),
        now=datetime(2026, 10, 4, 5, tzinfo=timezone.utc),
    )
    result["summary"]["issues"] = 99

    with pytest.raises(OperationsDashboardProjectionError, match="digest mismatch"):
        validate_operations_dashboard_projection(result)


def test_source_contract_and_spatial_hold_are_fixed():
    result = build_operations_dashboard_projection(
        [],
        system_health=_green_health(),
        now=datetime(2026, 10, 4, 5, tzinfo=timezone.utc),
    )

    assert result["source_contract"] == DASHBOARD_SOURCE_CONTRACT_V2
    assert result["spatial_office"] == {"status": "HOLD_BY_USER", "blocks_dashboard": False}


def test_waiting_approval_is_not_counted_as_running():
    result = build_operations_dashboard_projection(
        [
            _model(
                "a",
                "approval",
                "WAITING_APPROVAL",
                "2026-10-04T02:00:00+00:00",
                approval_required=True,
            )
        ],
        system_health=_green_health(),
        now=datetime(2026, 10, 4, 5, tzinfo=timezone.utc),
    )

    assert result["summary"]["running"] == 0
    assert result["summary"]["waiting_approval"] == 1
