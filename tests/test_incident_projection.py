from datetime import datetime, timezone
import unittest

from runtime.orchestrator.incident_projection import project_incidents


class IncidentProjectionTests(unittest.TestCase):
    def test_resolved_old_stall_is_historical(self):
        rows = ({
            "incident_id": "STALL-R1",
            "kind": "STALL_CONFIRMED",
            "opened_at": "2026-09-23T10:00:00+00:00",
            "last_observed_at": "2026-09-23T10:05:00+00:00",
            "evidence_ref": "evidence:stall-r1",
        },)
        incidents = project_incidents(
            current_state="RUNNING",
            current_state_ref="run:R1:healthy-generation-9",
            evidence_rows=rows,
            now=datetime(2026, 9, 24, tzinfo=timezone.utc),
        )
        self.assertEqual(incidents[0].state, "HISTORICAL")
        self.assertFalse(incidents[0].user_action_required)

    def test_current_stall_remains_open(self):
        rows = ({
            "incident_id": "STALL-R2",
            "kind": "STALL_CONFIRMED",
            "opened_at": "2026-09-24T00:00:00+00:00",
            "last_observed_at": "2026-09-24T00:01:00+00:00",
            "evidence_ref": "evidence:stall-r2",
        },)
        incidents = project_incidents(
            current_state="STALLED",
            current_state_ref="run:R2:stalled",
            evidence_rows=rows,
            now=datetime(2026, 9, 24, 0, 2, tzinfo=timezone.utc),
        )
        self.assertEqual(incidents[0].state, "OPEN")
        self.assertTrue(incidents[0].user_action_required)


    def test_stale_explicit_open_is_historical_when_current_state_healthy(self):
        rows = ({
            "incident_id": "STALL-R3",
            "kind": "STALL_CONFIRMED",
            "opened_at": "2026-09-24T00:00:00+00:00",
            "last_observed_at": "2026-09-24T00:01:00+00:00",
            "state": "OPEN",
            "evidence_ref": "evidence:stall-r3",
        },)
        incidents = project_incidents(
            current_state="RUNNING",
            current_state_ref="run:R3:healthy-generation-10",
            evidence_rows=rows,
            now=datetime(2026, 9, 24, 0, 10, tzinfo=timezone.utc),
        )
        self.assertEqual(incidents[0].state, "HISTORICAL")
        self.assertFalse(incidents[0].user_action_required)

    def test_stale_unresolved_without_current_binding_is_historical(self):
        rows = ({
            "incident_id": "STALL-R4",
            "kind": "STALL_CONFIRMED",
            "opened_at": "2026-09-24T00:00:00+00:00",
            "last_observed_at": "2026-09-24T00:01:00+00:00",
            "unresolved": True,
            "evidence_ref": "evidence:stall-r4",
        },)
        incidents = project_incidents(
            current_state="RUNNING",
            current_state_ref="run:R4:healthy-generation-11",
            evidence_rows=rows,
            now=datetime(2026, 9, 24, 0, 10, tzinfo=timezone.utc),
        )
        self.assertEqual(incidents[0].state, "HISTORICAL")
        self.assertFalse(incidents[0].user_action_required)

    def test_stale_unresolved_bound_to_current_state_ref_is_historical_when_current_state_healthy(self):
        ref = "run:R5:incident:STALL-R5"
        rows = ({
            "incident_id": "STALL-R5",
            "kind": "STALL_CONFIRMED",
            "opened_at": "2026-09-24T00:00:00+00:00",
            "last_observed_at": "2026-09-24T00:01:00+00:00",
            "unresolved": True,
            "current_state_ref": ref,
            "evidence_ref": "evidence:stall-r5",
        },)
        incidents = project_incidents(
            current_state="RUNNING",
            current_state_ref=ref,
            evidence_rows=rows,
            now=datetime(2026, 9, 24, 1, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(incidents[0].state, "HISTORICAL")
        self.assertFalse(incidents[0].user_action_required)


if __name__ == "__main__":
    unittest.main()
