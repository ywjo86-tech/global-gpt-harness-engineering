from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime.ai_office.state_store import AIOfficeStateStore
from runtime.orchestrator.monitor_health import build_monitor_health_receipt
from runtime.orchestrator.operations_current_attention import (
    build_current_attention_projection,
    current_attention_path,
    record_current_attention_projection,
)
from runtime.orchestrator.operations_dashboard_projection import build_operations_dashboard_projection
from runtime.orchestrator.operational_system_acceptance import (
    build_operational_system_acceptance,
    record_operational_system_acceptance,
)
import runtime.orchestrator.operations_dashboard_source as dashboard_source
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


def _write_system_acceptance(root, *, runtime, expected, created_at, blockers=()):
    attention = build_current_attention_projection(
        runtime_source_identity=runtime,
        blockers=list(blockers),
        observed_at=datetime.fromisoformat(created_at.replace("Z", "+00:00")),
    )
    gate = {
        "status": "PASS" if not blockers else "BLOCKED",
        "failures": [] if not blockers else ["ATTENTION_HEALTH:MONITOR_RECEIPT_BLOCKED"],
        "expected_runtime_source_identity": expected,
        "gate_evidence_sha256": "c" * 64,
    }
    record = build_operational_system_acceptance(
        runtime_source_identity=runtime,
        expected_runtime_source_identity=expected,
        registered_project_count=max(1, len({str(x.get("project_id") or "") for x in blockers})),
        post_change_gate=gate,
        current_attention_projection=attention,
        created_at=created_at,
    )
    record_operational_system_acceptance(root, record)
    return record


def _health(root):
    base = root / "operations-v2"
    base.mkdir(parents=True, exist_ok=True)
    (base / "attention-health.json").write_text(json.dumps({"result": "PASS"}))
    (base / "reconcile-timer-health.json").write_text(json.dumps({"result": "PASS"}))
    (base / "post-change-gate.json").write_text(json.dumps({"status": "PASS"}))
    (base / "operational-acceptance.json").write_text(json.dumps({"status": "ACCEPTED"}))


class OperationsDashboardSourceTests(unittest.TestCase):
    def test_source_uses_canonical_ai_office_state_store(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            _store(tmp_path, "project-a", "run-a", state="EXECUTION_IN_PROGRESS")

            models, invalid = discover_ai_office_operations_read_models(
                tmp_path,
                now=datetime.now(timezone.utc),
            )

            self.assertEqual(len(models), 1)
            self.assertEqual(invalid, ())
            model = models[0]
            self.assertEqual(model.project_id, "project-a")
            self.assertEqual(model.run_id, "run-a")
            self.assertEqual(model.normalized_state, "RUNNING")
            self.assertEqual(model.sources[0].source_component, "AI_OFFICE_STATE_STORE")

    def test_corrupt_newer_snapshot_becomes_invalid_observation_not_older_green(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
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

            self.assertEqual({model.run_id for model in models}, {"old"})
            self.assertEqual(len(invalid), 1)
            self.assertEqual(invalid[0].project_id, "project-a")
            self.assertEqual(invalid[0].run_id, "new")

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
            self.assertEqual(projection["recent_requests"][0]["run_id"], "new")
            self.assertEqual(projection["recent_requests"][0]["state"], "UNKNOWN")
            self.assertEqual(projection["data_quality"]["invalid_current_projects"], 1)

    def test_health_reader_is_bounded_and_missing_is_visible(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            _health(tmp_path)
            self.assertEqual(read_operations_dashboard_health(tmp_path), {
                "attention": "PASS",
                "reconcile": "PASS",
                "post_change": "PASS",
                "acceptance": "ACCEPTED",
            })

            (tmp_path / "operations-v2" / "reconcile-timer-health.json").unlink()
            self.assertEqual(
                read_operations_dashboard_health(tmp_path)["reconcile"],
                "UNAVAILABLE",
            )

    def test_strict_health_reader_blocks_runtime_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            base = tmp_path / "operations-v2"
            base.mkdir(parents=True, exist_ok=True)
            scanned = "2026-10-05T08:00:00+00:00"
            for name, filename in (
                ("ATTENTION_HEALTH", "attention-health.json"),
                ("RECONCILE_TIMER_HEALTH", "reconcile-timer-health.json"),
            ):
                receipt = build_monitor_health_receipt(
                    monitor_name=name,
                    runtime_source_identity="runtime:old",
                    search_root=tmp_path,
                    registered_job_count=1,
                    pending_current_event_count=0,
                    result="PASS",
                    scanned_at=scanned,
                )
                (base / filename).write_text(json.dumps(receipt.to_dict()))
            (base / "post-change-gate.json").write_text(json.dumps({
                "status": "PASS",
                "expected_runtime_source_identity": "runtime:old",
            }))
            _write_system_acceptance(
                tmp_path,
                runtime="runtime:old",
                expected="runtime:old",
                created_at=scanned,
            )

            health = read_operations_dashboard_health(
                tmp_path,
                now=datetime(2026, 10, 5, 8, 0, 30, tzinfo=timezone.utc),
                expected_runtime_source="runtime:new",
                fresh_after_seconds=180,
            )

            self.assertEqual(health, {
                "attention": "BLOCKED",
                "reconcile": "BLOCKED",
                "post_change": "BLOCKED",
                "acceptance": "BLOCKED",
            })

    def test_strict_health_reader_marks_stale_acceptance(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            base = tmp_path / "operations-v2"
            base.mkdir(parents=True, exist_ok=True)
            scanned = "2026-10-05T08:00:00+00:00"
            expected = "runtime:current"
            for name, filename in (
                ("ATTENTION_HEALTH", "attention-health.json"),
                ("RECONCILE_TIMER_HEALTH", "reconcile-timer-health.json"),
            ):
                receipt = build_monitor_health_receipt(
                    monitor_name=name,
                    runtime_source_identity=expected,
                    search_root=tmp_path,
                    registered_job_count=1,
                    pending_current_event_count=0,
                    result="PASS",
                    scanned_at=scanned,
                )
                (base / filename).write_text(json.dumps(receipt.to_dict()))
            (base / "post-change-gate.json").write_text(json.dumps({
                "status": "PASS",
                "expected_runtime_source_identity": expected,
            }))
            _write_system_acceptance(
                tmp_path,
                runtime=expected,
                expected=expected,
                created_at="2026-10-05T07:00:00+00:00",
            )

            health = read_operations_dashboard_health(
                tmp_path,
                now=datetime(2026, 10, 5, 8, 0, 30, tzinfo=timezone.utc),
                expected_runtime_source=expected,
                fresh_after_seconds=180,
            )

            self.assertEqual(health["attention"], "PASS")
            self.assertEqual(health["reconcile"], "PASS")
            self.assertEqual(health["post_change"], "PASS")
            self.assertEqual(health["acceptance"], "STALE")

    def test_live_projection_carries_typed_current_attention_into_alerts(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            now = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)
            expected = "runtime:new"
            attention = build_current_attention_projection(
                runtime_source_identity=expected,
                blockers=[{
                    "project_id": "P",
                    "run_id": "R",
                    "state": "BLOCKED",
                    "kind": "DEAD_LETTER",
                    "reason": "focused validation missing",
                    "current_gate": "G1",
                    "event_id": "a" * 64,
                }],
                observed_at=now,
            )
            record_current_attention_projection(current_attention_path(tmp_path), attention)
            with patch.object(
                dashboard_source,
                "read_operations_dashboard_jarvis_status",
                return_value={
                    "webapp": "AVAILABLE",
                    "memory": "AVAILABLE",
                    "llmwiki": "AVAILABLE",
                    "source_state": "CANONICAL_JARVIS_COMPACT_STATUS_V1",
                },
            ):
                projection = dashboard_source.build_live_operations_dashboard_projection(
                    tmp_path,
                    now=now + timedelta(seconds=30),
                    expected_operational_runtime_source=expected,
                )

            user_alerts = [item for item in projection["alerts"] if item["kind"] == "USER_ATTENTION"]
            self.assertEqual(len(user_alerts), 1)
            self.assertEqual(user_alerts[0]["title"], "P / BLOCKED")
            self.assertIn("focused validation missing", user_alerts[0]["detail"])


if __name__ == "__main__":
    unittest.main()
