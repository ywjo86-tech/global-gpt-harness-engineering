from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from runtime.orchestrator.operational_post_change_gate import (
    HOST_RUNNER_SERVICE, OCP_SERVICE, OCP_TIMER, RECONCILE_SERVICE, RECONCILE_TIMER,
    evaluate_post_change_gate,
)


class FakeObserver:
    def __init__(self, values):
        self.values = values
    def read(self, unit):
        return dict(self.values[unit])


def healthy_values():
    trigger = "Sun 2026-10-04 11:59:00 KST"
    return {
        OCP_TIMER: {"ActiveState":"active","SubState":"waiting","Result":"success","LastTriggerUSec":trigger},
        OCP_SERVICE: {"ActiveState":"inactive","SubState":"dead","Result":"success","ExecMainStatus":"0"},
        HOST_RUNNER_SERVICE: {"ActiveState":"active","SubState":"running","Result":"success","ExecMainStatus":"0"},
        RECONCILE_TIMER: {"ActiveState":"active","SubState":"waiting","Result":"success","LastTriggerUSec":trigger},
        RECONCILE_SERVICE: {"ActiveState":"inactive","SubState":"dead","Result":"success","ExecMainStatus":"0"},
    }


def write_policy(root: Path, services):
    project=root/"project"; project.mkdir()
    path=root/"diag.json"
    path.write_text(json.dumps({
        "schema_version":"orchestration.read-only-host-diagnostic-config.v1",
        "roots":{"project":str(project)},
        "user_services":list(services),
        "limits":{"max_bytes":1024,"max_lines":20,"timeout_seconds":5},
    }))
    return path


class OperationalPostChangeGateTests(unittest.TestCase):
    def test_all_required_conditions_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            policy=write_policy(root,[OCP_SERVICE,OCP_TIMER,RECONCILE_SERVICE,RECONCILE_TIMER])
            result=evaluate_post_change_gate(
                diagnostic_config=policy, attention_watch_enabled=True, timer_watch_enabled=True,
                observer=FakeObserver(healthy_values()), now=datetime(2026,10,4,12,0,0),
            )
        self.assertEqual(result["status"],"PASS")
        self.assertEqual(result["failures"],[])

    def test_stopped_reconcile_timer_blocks_gate(self):
        values=healthy_values()
        values[RECONCILE_TIMER]["ActiveState"]="inactive"
        values[RECONCILE_TIMER]["SubState"]="dead"
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            policy=write_policy(root,[OCP_SERVICE,OCP_TIMER,RECONCILE_SERVICE,RECONCILE_TIMER])
            result=evaluate_post_change_gate(
                diagnostic_config=policy, attention_watch_enabled=True, timer_watch_enabled=True,
                observer=FakeObserver(values), now=datetime(2026,10,4,12,0,0),
            )
        self.assertEqual(result["status"],"BLOCKED")
        self.assertIn(f"{RECONCILE_TIMER}:NOT_ACTIVE",result["failures"])

    def test_stale_timer_blocks_gate(self):
        values=healthy_values()
        values[OCP_TIMER]["LastTriggerUSec"]="Sun 2026-10-04 11:50:00 KST"
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            policy=write_policy(root,[OCP_SERVICE,OCP_TIMER,RECONCILE_SERVICE,RECONCILE_TIMER])
            result=evaluate_post_change_gate(
                diagnostic_config=policy, attention_watch_enabled=True, timer_watch_enabled=True,
                observer=FakeObserver(values), now=datetime(2026,10,4,12,0,0),
            )
        self.assertIn(f"{OCP_TIMER}:TRIGGER_STALE",result["failures"])

    def test_missing_diagnostic_coverage_blocks_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            policy=write_policy(root,[OCP_SERVICE])
            result=evaluate_post_change_gate(
                diagnostic_config=policy, attention_watch_enabled=True, timer_watch_enabled=True,
                observer=FakeObserver(healthy_values()), now=datetime(2026,10,4,12,0,0),
            )
        self.assertEqual(result["status"],"BLOCKED")
        self.assertTrue(any(x.startswith("DIAGNOSTIC_COVERAGE_MISSING:") for x in result["failures"]))

    def test_disabled_external_watch_blocks_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            policy=write_policy(root,[OCP_SERVICE,OCP_TIMER,RECONCILE_SERVICE,RECONCILE_TIMER])
            result=evaluate_post_change_gate(
                diagnostic_config=policy, attention_watch_enabled=False, timer_watch_enabled=True,
                observer=FakeObserver(healthy_values()), now=datetime(2026,10,4,12,0,0),
            )
        self.assertIn("ATTENTION_WATCH_DISABLED",result["failures"])


if __name__=="__main__":
    unittest.main()
