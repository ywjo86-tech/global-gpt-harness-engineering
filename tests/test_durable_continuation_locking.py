from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.gate_continuation_transaction import GateContinuationTransactionStore
from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor, ProductionFullPlanError


class DurableContinuationLockingTests(unittest.TestCase):
    def supervisor(self, root: str) -> DurableFullPlanSupervisor:
        return DurableFullPlanSupervisor(
            root, project_id="P", run_id="R", gates=("G1",),
            min_disk_free_bytes=0, min_inode_free=0, min_memory_available_bytes=0,
        )

    def test_stale_epoch_cannot_enter_continuation_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            supervisor = self.supervisor(directory)
            stale = supervisor.claim_attested_continuation_owner(expected_gate_id="G1")
            current = supervisor.claim_attested_continuation_owner(expected_gate_id="G1")
            self.assertGreater(current.epoch, stale.epoch)
            store = GateContinuationTransactionStore(directory, project_id="P", run_id="R")
            with self.assertRaisesRegex(ProductionFullPlanError, "stale.*epoch"):
                with supervisor.continuation_transaction(stale, store):
                    self.fail("stale owner entered transaction scope")

    def test_current_owner_enters_run_then_transaction_lock_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            supervisor = self.supervisor(directory)
            token = supervisor.claim_attested_continuation_owner(expected_gate_id="G1")
            store = GateContinuationTransactionStore(directory, project_id="P", run_id="R")
            with supervisor.continuation_transaction(token, store):
                supervisor.assert_current_epoch_locked(token)
            supervisor.assert_current_epoch(token)

    def test_transaction_lock_without_outer_run_lock_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GateContinuationTransactionStore(directory, project_id="P", run_id="R")
            with self.assertRaisesRegex(Exception, "run lock.*outer|lock order"):
                with store.transaction_lock("G1"):
                    self.fail("transaction lock acquired without run lock")

    def test_claiming_new_owner_fences_prior_owner_without_double_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            supervisor = self.supervisor(directory)
            first = supervisor.claim_attested_continuation_owner(expected_gate_id="G1")
            second = supervisor.claim_attested_continuation_owner(expected_gate_id="G1")
            self.assertEqual(second.epoch, first.epoch + 1)
            with self.assertRaisesRegex(ProductionFullPlanError, "stale.*epoch"):
                supervisor.assert_current_epoch(first)
            supervisor.assert_current_epoch(second)
            state, _ = supervisor.load()
            self.assertEqual(state["continuation_owner"]["epoch"], second.epoch)
            self.assertEqual(state["continuation_owner"]["gate_id"], "G1")


if __name__ == "__main__":
    unittest.main()
