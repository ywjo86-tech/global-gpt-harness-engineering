from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from runtime.orchestrator.ocpv2_runtime_service import full_plan_execution_health
from runtime.orchestrator.operational_post_change_gate import (
    HOST_RUNNER_SERVICE,
    OCP_SERVICE,
    OCP_TIMER,
    RECONCILE_SERVICE,
    RECONCILE_TIMER,
    evaluate_post_change_gate,
)
from runtime.orchestrator.user_service_observer import UserServiceObserverError


NOW = datetime(2026, 10, 4, 12, 0, 0)
FRESH = "Sun 2026-10-04 11:59:00 KST"
STALE = "Sun 2026-10-04 11:50:00 KST"


class DictObserver:
    def __init__(self, values):
        self.values = values

    def read(self, unit):
        return dict(self.values[unit])


class FailingObserver:
    def read(self, unit):
        raise UserServiceObserverError("SERVICE_QUERY_FAILED")


def healthy_values():
    return {
        OCP_TIMER: {
            "ActiveState": "active", "SubState": "waiting",
            "Result": "success", "LastTriggerUSec": FRESH,
        },
        OCP_SERVICE: {
            "ActiveState": "inactive", "SubState": "dead",
            "Result": "success", "ExecMainStatus": "0",
        },
        HOST_RUNNER_SERVICE: {
            "ActiveState": "active", "SubState": "running",
            "Result": "success", "ExecMainStatus": "0",
        },
        RECONCILE_TIMER: {
            "ActiveState": "active", "SubState": "waiting",
            "Result": "success", "LastTriggerUSec": FRESH,
        },
        RECONCILE_SERVICE: {
            "ActiveState": "inactive", "SubState": "dead",
            "Result": "success", "ExecMainStatus": "0",
        },
    }


def write_policy(root: Path, services):
    project = root / "project"
    project.mkdir()
    path = root / "diag.json"
    path.write_text(json.dumps({
        "schema_version": "orchestration.read-only-host-diagnostic-config.v1",
        "roots": {"project": str(project)},
        "user_services": list(services),
        "limits": {"max_bytes": 1024, "max_lines": 20, "timeout_seconds": 5},
    }))
    return path


class OperationalFailureReproductionTests(unittest.TestCase):
    def _gate(self, values, *, attention=True, timer_watch=True, services=None):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            policy = write_policy(
                root,
                services or [OCP_SERVICE, OCP_TIMER, RECONCILE_SERVICE, RECONCILE_TIMER],
            )
            return evaluate_post_change_gate(
                diagnostic_config=policy,
                attention_watch_enabled=attention,
                timer_watch_enabled=timer_watch,
                observer=DictObserver(values),
                now=NOW,
                stale_after_seconds=180,
            )

    def _ocp_health(self, values):
        return full_plan_execution_health(
            DictObserver({
                RECONCILE_TIMER: values[RECONCILE_TIMER],
                RECONCILE_SERVICE: values[RECONCILE_SERVICE],
            }),
            now=NOW,
            stale_after_seconds=180,
        )

    def test_healthy_then_timer_stop_then_restore_has_no_false_green(self):
        values = healthy_values()
        self.assertEqual(self._ocp_health(values)["status"], "HEALTHY")
        self.assertEqual(self._gate(values)["status"], "PASS")

        values[RECONCILE_TIMER]["ActiveState"] = "inactive"
        values[RECONCILE_TIMER]["SubState"] = "dead"
        self.assertEqual(self._ocp_health(values)["status"], "DEGRADED")
        self.assertEqual(self._gate(values)["status"], "BLOCKED")

        values = healthy_values()
        self.assertEqual(self._ocp_health(values)["status"], "HEALTHY")
        self.assertEqual(self._gate(values)["status"], "PASS")

    def test_stale_trigger_is_degraded_and_blocked_across_both_layers(self):
        values = healthy_values()
        values[RECONCILE_TIMER]["LastTriggerUSec"] = STALE
        health = self._ocp_health(values)
        gate = self._gate(values)
        self.assertEqual(health["status"], "DEGRADED")
        self.assertIn("RECONCILE_TIMER_TRIGGER_STALE", health["reason"])
        self.assertEqual(gate["status"], "BLOCKED")
        self.assertIn(f"{RECONCILE_TIMER}:TRIGGER_STALE", gate["failures"])

    def test_failed_reconcile_service_is_degraded_and_blocked_across_both_layers(self):
        values = healthy_values()
        values[RECONCILE_SERVICE].update({
            "ActiveState": "failed", "SubState": "failed",
            "Result": "exit-code", "ExecMainStatus": "1",
        })
        health = self._ocp_health(values)
        gate = self._gate(values)
        self.assertEqual(health["status"], "DEGRADED")
        self.assertIn("RECONCILE_SERVICE_NOT_HEALTHY", health["reason"])
        self.assertEqual(gate["status"], "BLOCKED")
        self.assertIn(f"{RECONCILE_SERVICE}:LAST_RUN_FAILED", gate["failures"])

    def test_observation_failure_never_becomes_green(self):
        health = full_plan_execution_health(FailingObserver(), now=NOW)
        self.assertEqual(health["status"], "DEGRADED")
        self.assertEqual(health["reason"], "RECONCILE_HEALTH_UNAVAILABLE")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            policy = write_policy(
                root, [OCP_SERVICE, OCP_TIMER, RECONCILE_SERVICE, RECONCILE_TIMER]
            )
            gate = evaluate_post_change_gate(
                diagnostic_config=policy,
                attention_watch_enabled=True,
                timer_watch_enabled=True,
                observer=FailingObserver(),
                now=NOW,
            )
        self.assertEqual(gate["status"], "BLOCKED")
        self.assertTrue(gate["failures"][0].startswith("SERVICE_OBSERVATION_FAILED:"))

    def test_monitoring_or_diagnostic_gap_blocks_completion_even_when_execution_is_healthy(self):
        values = healthy_values()
        self.assertEqual(self._ocp_health(values)["status"], "HEALTHY")

        monitor_gap = self._gate(values, attention=False)
        self.assertEqual(monitor_gap["status"], "BLOCKED")
        self.assertIn("ATTENTION_WATCH_DISABLED", monitor_gap["failures"])

        coverage_gap = self._gate(values, services=[OCP_SERVICE])
        self.assertEqual(coverage_gap["status"], "BLOCKED")
        self.assertTrue(
            any(item.startswith("DIAGNOSTIC_COVERAGE_MISSING:") for item in coverage_gap["failures"])
        )


if __name__ == "__main__":
    unittest.main()
