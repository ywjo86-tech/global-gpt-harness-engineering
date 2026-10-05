from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from runtime.orchestrator.operations_current_attention import (
    CURRENT_ATTENTION_SOURCE_V1,
    CurrentAttentionProjectionError,
    attention_projection_to_dashboard_alerts,
    build_current_attention_projection,
    read_current_attention_projection,
    record_current_attention_projection,
)


NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


def blocker() -> dict[str, str]:
    return {
        "project_id": "P",
        "run_id": "R",
        "state": "BLOCKED",
        "kind": "BLOCKED",
        "reason": "RETRY_BUDGET_EXHAUSTED",
        "current_gate": "GATE-001",
        "delivery_class": "DEFERRED_INCIDENT",
        "event_id": "a" * 64,
    }


def test_projection_is_bounded_digest_bound_and_alertable(tmp_path):
    value = build_current_attention_projection(
        runtime_source_identity="head:abc",
        blockers=[blocker()],
        observed_at=NOW,
    )
    target = tmp_path / "operations-v2" / "current-attention.json"
    record_current_attention_projection(target, value)
    loaded = read_current_attention_projection(
        tmp_path,
        now=NOW + timedelta(seconds=30),
        expected_runtime_source="head:abc",
    )
    assert loaded["source_state"] == CURRENT_ATTENTION_SOURCE_V1
    assert loaded["items"][0]["reason"] == "RETRY_BUDGET_EXHAUSTED"
    alerts = attention_projection_to_dashboard_alerts(loaded)
    assert alerts[0]["severity"] == "ERROR"
    assert alerts[0]["kind"] == "USER_ATTENTION"


def test_projection_fails_closed_on_stale_runtime_mismatch_and_tamper(tmp_path):
    value = build_current_attention_projection(
        runtime_source_identity="head:abc",
        blockers=[blocker()],
        observed_at=NOW,
    )
    target = tmp_path / "operations-v2" / "current-attention.json"
    record_current_attention_projection(target, value)
    assert read_current_attention_projection(
        tmp_path,
        now=NOW + timedelta(seconds=181),
        expected_runtime_source="head:abc",
    )["source_state"] == "STALE"
    assert read_current_attention_projection(
        tmp_path,
        now=NOW + timedelta(seconds=30),
        expected_runtime_source="head:def",
    )["source_state"] == "RUNTIME_MISMATCH"
    raw = json.loads(target.read_text())
    raw["items"][0]["reason"] = "tampered"
    target.write_text(json.dumps(raw))
    assert read_current_attention_projection(
        tmp_path,
        now=NOW + timedelta(seconds=30),
        expected_runtime_source="head:abc",
    )["source_state"] == "INVALID"


def test_projection_contains_no_control_authority_or_raw_payload():
    value = build_current_attention_projection(
        runtime_source_identity="head:abc",
        blockers=[{
            **blocker(),
            "control_authority": "MUST_NOT_LEAK",
            "raw_payload": {"secret": "MUST_NOT_LEAK"},
        }],
        observed_at=NOW,
    )
    encoded = json.dumps(value, sort_keys=True)
    assert "MUST_NOT_LEAK" not in encoded
    assert "control_authority" not in encoded
    assert "raw_payload" not in encoded


def test_projection_rejects_unsafe_output_symlink(tmp_path):
    value = build_current_attention_projection(
        runtime_source_identity="head:abc",
        blockers=[blocker()],
        observed_at=NOW,
    )
    real = tmp_path / "real.json"
    real.write_text("{}")
    link = tmp_path / "attention.json"
    link.symlink_to(real)
    with pytest.raises(CurrentAttentionProjectionError, match="unsafe"):
        record_current_attention_projection(link, value)
