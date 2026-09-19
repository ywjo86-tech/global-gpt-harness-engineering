from __future__ import annotations

import unittest

from runtime.ai_office.contracts import OFFICE_STATE_SNAPSHOT_SCHEMA_V1, OfficeStateSnapshotV1
from runtime.ai_office.reporting import build_office_report
from runtime.ai_office.workflow import FullPlanCompletionRefV1


class AIOfficeReportingTest(unittest.TestCase):
    def completion(self):
        return FullPlanCompletionRefV1("full-plan-run", "GATE-005", "gate:go", "b" * 64, "full-plan:fanin-001", "c" * 64)

    def snapshot(self):
        completion = self.completion()
        return OfficeStateSnapshotV1(
            OFFICE_STATE_SNAPSHOT_SCHEMA_V1,
            "PHASE5_AI_OFFICE_HARNESS_UPGRADE",
            "report-run",
            7,
            "REVIEW_PENDING",
            "plan:approved",
            "baseline:approved",
            ("workflow:001", f"full-plan-completion:{completion.completion_digest}"),
            "approval:pending",
            "manual-action:pending",
            "a" * 64,
        )

    def test_015_assignment_and_fanin_are_external_refs_only(self) -> None:
        report = build_office_report(
            self.snapshot(),
            external_assignment_ref="full-plan:assignment-001",
            full_plan_completion=self.completion(),
        )
        payload = report.to_dict()
        self.assertEqual(payload["external_assignment_ref"], "full-plan:assignment-001")
        self.assertEqual(payload["external_fanin_ref"], "full-plan:fanin-001")
        self.assertEqual(len(payload["full_plan_completion_digest"]), 64)
        self.assertFalse({"assignment_decision", "fanin_decision", "gate_decision", "completion_decision"}.intersection(payload))

    def test_025_report_is_reproducible_and_does_not_mutate_source_state(self) -> None:
        snapshot = self.snapshot()
        before = snapshot.to_dict()
        first = build_office_report(
            snapshot,
            external_assignment_ref="full-plan:assignment-001",
            full_plan_completion=self.completion(),
            observation_refs=("observation:b", "observation:a"),
            recovery_refs=("recovery:001",),
        )
        second = build_office_report(
            snapshot,
            external_assignment_ref="full-plan:assignment-001",
            full_plan_completion=self.completion(),
            observation_refs=("observation:a", "observation:b"),
            recovery_refs=("recovery:001",),
        )
        self.assertEqual(first.report_digest, second.report_digest)
        self.assertEqual(snapshot.to_dict(), before)
        self.assertEqual(first.kpi.observation_ref_count, 2)
        self.assertEqual(first.kpi.recovery_ref_count, 1)
        self.assertFalse({"effect_status", "canonical_effect", "provider_truth", "action_truth"}.intersection(first.to_dict()))

    def test_025_unbound_fanin_evidence_is_rejected(self) -> None:
        snapshot = OfficeStateSnapshotV1(
            OFFICE_STATE_SNAPSHOT_SCHEMA_V1, "P", "R", 1, "REVIEW_PENDING",
            "plan:approved", "baseline:approved", ("workflow:001",), "", "", "a" * 64,
        )
        with self.assertRaisesRegex(Exception, "FULL_PLAN_COMPLETION_BINDING_MISMATCH"):
            build_office_report(snapshot, full_plan_completion=self.completion())


if __name__ == "__main__":
    unittest.main()
