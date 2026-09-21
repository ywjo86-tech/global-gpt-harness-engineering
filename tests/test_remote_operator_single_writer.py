from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.gate_continuation_transaction import GateContinuationTransactionStore
from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor, ProductionFullPlanError
from runtime.orchestrator.remote_operator_ingress import execute_remote_directive_in_canonical_transaction


class RemoteOperatorSingleWriterTests(unittest.TestCase):
    def _runtime(self, root: Path):
        supervisor = DurableFullPlanSupervisor(root, project_id="P1", run_id="R1", gates=("G1",))
        tx = GateContinuationTransactionStore(root, project_id="P1", run_id="R1")
        return supervisor, tx

    def test_newer_owner_epoch_fences_previous_owner(self):
        with tempfile.TemporaryDirectory() as td:
            supervisor, _ = self._runtime(Path(td))
            first = supervisor.claim_attested_continuation_owner(expected_gate_id="G1")
            second = supervisor.claim_attested_continuation_owner(expected_gate_id="G1")
            with self.assertRaisesRegex(ProductionFullPlanError, "stale continuation owner epoch"):
                supervisor.assert_current_epoch(first)
            self.assertEqual(supervisor.assert_current_epoch(second)["continuation_owner"]["epoch"], second.epoch)

    def test_prelock_and_inlock_cas_allow_one_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            supervisor, tx = self._runtime(Path(td))
            canonical = {"sha": "a" * 64}
            mutations = []

            def mutate(token):
                mutations.append(token.epoch)
                canonical["sha"] = "b" * 64
                return {"status": "COMPLETED", "owner_epoch": token.epoch}

            result = execute_remote_directive_in_canonical_transaction(
                supervisor, tx, expected_gate_id="G1", expected_state_sha256="a" * 64,
                canonical_state_sha256=lambda: canonical["sha"], mutation=mutate,
            )
            self.assertEqual(result["status"], "COMPLETED")
            self.assertEqual(len(mutations), 1)
            with self.assertRaisesRegex(ProductionFullPlanError, "STALE_DIRECTIVE"):
                execute_remote_directive_in_canonical_transaction(
                    supervisor, tx, expected_gate_id="G1", expected_state_sha256="a" * 64,
                    canonical_state_sha256=lambda: canonical["sha"], mutation=mutate,
                )
            self.assertEqual(len(mutations), 1)

    def test_inlock_double_cas_blocks_state_change_before_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            supervisor, tx = self._runtime(Path(td))
            calls = {"read": 0, "mutate": 0}

            def state_digest():
                calls["read"] += 1
                return "a" * 64 if calls["read"] == 1 else "b" * 64

            def mutate(_token):
                calls["mutate"] += 1
                return {"status": "COMPLETED"}

            with self.assertRaisesRegex(ProductionFullPlanError, "STALE_DIRECTIVE"):
                execute_remote_directive_in_canonical_transaction(
                    supervisor, tx, expected_gate_id="G1", expected_state_sha256="a" * 64,
                    canonical_state_sha256=state_digest, mutation=mutate,
                )
            self.assertEqual(calls["mutate"], 0)

    def test_reconcile_and_remote_sources_converge_on_same_entry_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            supervisor, tx = self._runtime(Path(td))
            canonical = {"sha": "a" * 64}
            mutations = []

            def mutation(source):
                def apply(_token):
                    mutations.append(source)
                    canonical["sha"] = "b" * 64
                    return {"source": source}
                return apply

            execute_remote_directive_in_canonical_transaction(
                supervisor, tx, expected_gate_id="G1", expected_state_sha256="a" * 64,
                canonical_state_sha256=lambda: canonical["sha"], mutation=mutation("remote"),
            )
            with self.assertRaisesRegex(ProductionFullPlanError, "STALE_DIRECTIVE"):
                execute_remote_directive_in_canonical_transaction(
                    supervisor, tx, expected_gate_id="G1", expected_state_sha256="a" * 64,
                    canonical_state_sha256=lambda: canonical["sha"], mutation=mutation("reconcile"),
                )
            self.assertEqual(mutations, ["remote"])


if __name__ == "__main__":
    unittest.main()
