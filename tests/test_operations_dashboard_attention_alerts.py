from __future__ import annotations

from datetime import datetime, timezone
import unittest

from runtime.orchestrator.operations_dashboard_projection import (
    build_operations_dashboard_projection,
)


class OperationsDashboardAttentionAlertsTests(unittest.TestCase):
    def test_current_attention_is_visible_as_dashboard_alert(self):
        projection = build_operations_dashboard_projection(
            (),
            system_health={
                "attention": "BLOCKED",
                "reconcile": "PASS",
                "post_change": "BLOCKED",
                "acceptance": "BLOCKED",
            },
            attention_alerts=({
                "kind": "USER_ATTENTION",
                "severity": "ERROR",
                "title": "ai-commerce / BLOCKED",
                "detail": "GATE-001: RETRY_BUDGET_EXHAUSTED",
                "source_ref": "attention:" + "a" * 64,
            },),
            now=datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc),
        )
        alerts = projection["alerts"]
        self.assertTrue(any(
            item["kind"] == "USER_ATTENTION"
            and item["severity"] == "ERROR"
            and "RETRY_BUDGET_EXHAUSTED" in item["detail"]
            for item in alerts
        ))

    def test_current_attention_does_not_grant_control_authority(self):
        projection = build_operations_dashboard_projection(
            (),
            system_health={
                "attention": "BLOCKED",
                "reconcile": "PASS",
                "post_change": "BLOCKED",
                "acceptance": "BLOCKED",
            },
            attention_alerts=({
                "kind": "USER_ATTENTION",
                "severity": "ERROR",
                "title": "P / BLOCKED",
                "detail": "operator action required",
                "source_ref": "attention:current-state",
            },),
            now=datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc),
        )
        encoded = str(projection)
        self.assertNotIn("approve_action", encoded)
        self.assertNotIn("resume_action", encoded)
        self.assertNotIn("provider_reroute", encoded)


if __name__ == "__main__":
    unittest.main()
