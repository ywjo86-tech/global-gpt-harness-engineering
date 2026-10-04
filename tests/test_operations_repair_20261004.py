from __future__ import annotations
import json, socket, tempfile, threading, time, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.attention_monitor_health import build_attention_health
from runtime.orchestrator.operational_post_change_gate import evaluate_post_change_gate
from runtime.orchestrator.production_execution_gateway import UnixSocketHostRunner, GatewayError

class _Observer:
    def read(self, unit):
        if unit.endswith(".timer"):
            return {"ActiveState":"active","SubState":"waiting","Result":"success",
                    "LastTriggerUSec":"Sun 2026-10-04 16:00:00 KST"}
        if unit=="ocpv2-host-runner.service":
            return {"ActiveState":"active","SubState":"running","Result":"success","ExecMainStatus":"0"}
        return {"ActiveState":"inactive","SubState":"dead","Result":"success","ExecMainStatus":"0"}

class OperationsRepairTests(unittest.TestCase):
    def test_attention_health_filters_terminal_history(self):
        with patch("runtime.orchestrator.attention_monitor_health.discover_registered_jobs", return_value=[{}]),              patch("runtime.orchestrator.attention_monitor_health.discover_pending_attention",
                   return_value=[{"state":"COMPLETED","event_id":"old"},{"state":"RUNNING","event_id":"new"}]):
            value=build_attention_health(".")
        self.assertEqual(value["current_attention_count"],1)
        self.assertEqual(value["status"],"ATTENTION_REQUIRED")

    def test_fresh_monitor_receipt_satisfies_attention_health(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); policy=root/"policy.json"; receipt=root/"receipt.json"
            policy.write_text(json.dumps({"schema_version":"orchestration.read-only-host-diagnostic-policy.v1",
                "allowed_commands":["systemctl_show"],"user_services":["ocpv2.service","ocpv2.timer",
                "global-gpt-harness-full-plan-reconcile.service","global-gpt-harness-full-plan-reconcile.timer"],
                "allowed_paths":[]}),encoding="utf-8")
            # Use production builder to guarantee digest shape.
            with patch("runtime.orchestrator.attention_monitor_health.discover_registered_jobs",return_value=[]),                  patch("runtime.orchestrator.attention_monitor_health.discover_pending_attention",return_value=[]):
                from runtime.orchestrator.attention_monitor_health import write_attention_health
                write_attention_health(".",receipt)
            result=evaluate_post_change_gate(diagnostic_config=policy,attention_watch_enabled=False,
                timer_watch_enabled=True,monitor_health_receipt=receipt,observer=_Observer(),
                now=datetime(2026,10,4,16,0,10))
            self.assertNotIn("ATTENTION_WATCH_DISABLED",result["failures"])

    def test_host_runner_no_client_exits_on_accept_timeout(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            runner=UnixSocketHostRunner(root/"runner.sock",root/"ledger")
            started=time.monotonic()
            with self.assertRaisesRegex(GatewayError,"HOST_RUNNER_ACCEPT_TIMEOUT"):
                runner.serve_once(timeout=0.05)
            self.assertLess(time.monotonic()-started,1.0)
            self.assertFalse((root/"runner.sock").exists())

if __name__=="__main__": unittest.main()
