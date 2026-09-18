from __future__ import annotations

import json
import tempfile
import unittest

from runtime.ai_office.contracts import (
    AIOfficeContractError,
    OFFICE_STATE_SNAPSHOT_SCHEMA_V1,
    OfficeStateSnapshotV1,
)
from runtime.ai_office.state_store import AIOfficeStateStore, AIOfficeStateStoreError


class AIOfficeStateStoreTest(unittest.TestCase):
    def make_store(self, root: str) -> AIOfficeStateStore:
        return AIOfficeStateStore(
            root,
            project_id="PHASE5_AI_OFFICE_HARNESS_UPGRADE",
            run_id="fixture-run",
        )

    def test_010_snapshot_and_journal_rehydrate_with_pending_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            initial = store.initialize(approved_plan_ref="plan:approved", baseline_ref="baseline:pre-ph5")
            self.assertEqual(initial.revision, 0)
            store.transition(
                to_state="WAITING_APPROVAL",
                reason_ref="reason:approval",
                pending_approval_ref="approval:pending",
            )
            final = store.transition(
                to_state="WAITING_STATE_CHANGE_AUTHORITY",
                reason_ref="reason:action-unavailable",
                pending_manual_action_ref="manual-action:pending",
            )
            restarted = self.make_store(directory).load()
            self.assertEqual(restarted.to_dict(), final.to_dict())
            self.assertEqual(restarted.pending_approval_ref, "approval:pending")
            self.assertEqual(restarted.pending_manual_action_ref, "manual-action:pending")
            self.assertEqual(restarted.revision, 2)
            first, second = map(json.loads, store.journal_path.read_text().splitlines())
            self.assertEqual(second["previous_record_digest"], first["record_digest"])

    def test_010_snapshot_corruption_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            store.initialize(approved_plan_ref="plan:approved", baseline_ref="baseline:pre-ph5")
            payload = json.loads(store.snapshot_path.read_text())
            payload["workflow_state"] = "COMPLETE"
            store.snapshot_path.write_text(json.dumps(payload))
            with self.assertRaises(AIOfficeStateStoreError):
                store.load()

    def test_010_journal_corruption_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            store.initialize(approved_plan_ref="plan:approved", baseline_ref="baseline:pre-ph5")
            store.transition(to_state="INTAKE_READY", reason_ref="reason:intake")
            record = json.loads(store.journal_path.read_text())
            record["previous_record_digest"] = "f" * 64
            store.journal_path.write_text(json.dumps(record) + "\n")
            with self.assertRaises(AIOfficeStateStoreError):
                store.load()

    def test_010_owned_state_rejects_external_runtime_truth_fields(self) -> None:
        payload = OfficeStateSnapshotV1(
            OFFICE_STATE_SNAPSHOT_SCHEMA_V1,
            "P", "R", 0, "NEW", "plan:x", "base:x",
        ).to_dict()
        payload["provider_ref"] = "external-runtime-ref"
        with self.assertRaises(AIOfficeContractError):
            OfficeStateSnapshotV1.from_mapping(payload)


if __name__ == "__main__":
    unittest.main()
