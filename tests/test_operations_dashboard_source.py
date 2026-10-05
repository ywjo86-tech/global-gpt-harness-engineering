from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from runtime.ai_office.state_store import AIOfficeStateStore
from runtime.orchestrator.operations_dashboard_projection import build_operations_dashboard_projection
from runtime.orchestrator.operations_dashboard_source import (
    discover_ai_office_operations_read_models,
    read_operations_dashboard_health,
)


def _store(root, project, run, *, state="INTAKE_READY"):
    store = AIOfficeStateStore(root, project_id=project, run_id=run)
    store.initialize(
        approved_plan_ref="plan:" + "1" * 64,
        baseline_ref="head:" + "a" * 40,
        workflow_state=state,
    )
    return store


def _health(root):
    base = root / "operations-v2"
    base.mkdir(parents=True, exist_ok=True)
    (base / "attention-health.json").write_text(json.dumps({"result": "PASS"}))
    (base / "reconcile-timer-health.json").write_text(json.dumps({"result": "PASS"}))
    (base / "post-change-gate.json").write_text(json.dumps({"status": "PASS"}))
    (base / "operational-acceptance.json").write_text(json.dumps({"status": "ACCEPTED"}))


def test_source_uses_canonical_ai_office_state_store(tmp_path):
    _store(tmp_path, "project-a", "run-a", state="EXECUTION_IN_PROGRESS")

    models, invalid = discover_ai_office_operations_read_models(
        tmp_path,
        now=datetime.now(timezone.utc),
    )

    assert len(models) == 1
    assert invalid == ()
    model = models[0]
    assert model.project_id == "project-a"
    assert model.run_id == "run-a"
    assert model.normalized_state == "RUNNING"
    assert model.sources[0].source_component == "AI_OFFICE_STATE_STORE"


def test_corrupt_newer_snapshot_becomes_invalid_observation_not_older_green(tmp_path):
    old = _store(tmp_path, "project-a", "old", state="COMPLETE")
    new = _store(tmp_path, "project-a", "new", state="EXECUTION_IN_PROGRESS")

    old_time = 1_760_000_000
    new_time = old_time + 10
    os.utime(old.snapshot_path, (old_time, old_time))
    payload = json.loads(new.snapshot_path.read_text())
    payload["snapshot_digest"] = "0" * 64
    new.snapshot_path.write_text(json.dumps(payload))
    os.utime(new.snapshot_path, (new_time, new_time))

    models, invalid = discover_ai_office_operations_read_models(
        tmp_path,
        now=datetime.now(timezone.utc),
    )

    assert {model.run_id for model in models} == {"old"}
    assert len(invalid) == 1
    assert invalid[0].project_id == "project-a"
    assert invalid[0].run_id == "new"

    projection = build_operations_dashboard_projection(
        models,
        invalid_current=invalid,
        system_health={
            "attention": "PASS",
            "reconcile": "PASS",
            "post_change": "PASS",
            "acceptance": "ACCEPTED",
        },
        now=datetime(2026, 10, 4, 5, tzinfo=timezone.utc),
    )
    assert projection["recent_requests"][0]["run_id"] == "new"
    assert projection["recent_requests"][0]["state"] == "UNKNOWN"
    assert projection["data_quality"]["invalid_current_projects"] == 1


def test_health_reader_is_bounded_and_missing_is_visible(tmp_path):
    _health(tmp_path)
    assert read_operations_dashboard_health(tmp_path) == {
        "attention": "PASS",
        "reconcile": "PASS",
        "post_change": "PASS",
        "acceptance": "ACCEPTED",
    }

    (tmp_path / "operations-v2" / "reconcile-timer-health.json").unlink()
    assert read_operations_dashboard_health(tmp_path)["reconcile"] == "UNAVAILABLE"
