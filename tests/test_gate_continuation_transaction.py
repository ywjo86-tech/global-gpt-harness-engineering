from __future__ import annotations
import tempfile, unittest
from pathlib import Path

class GateContinuationTransactionTests(unittest.TestCase):
    def api(self):
        try:
            from runtime.orchestrator.gate_continuation_transaction import GateContinuationTransactionStore, TransactionError
        except ModuleNotFoundError as exc:
            self.fail(f"transaction module missing: {exc}")
        return GateContinuationTransactionStore, TransactionError

    def test_durable_dispositions_round_trip_and_bind_prior_phase(self):
        Store, _ = self.api()
        for disposition in ("BLOCKED", "USER_DECISION_REQUIRED", "DELEGATED_RUNTIME_MIGRATION", "ROLLED_BACK"):
            with self.subTest(disposition=disposition), tempfile.TemporaryDirectory() as d:
                store = Store(Path(d), project_id="P", run_id="R")
                tx = store.create(gate_id="G", authority_core_sha256="a"*64, contract_sha256="b"*64)
                tx = store.transition("G", prior_phase="PREPARED", disposition=disposition,
                    reason="TEST_REASON", binding_digests={"evidence":"c"*64}, recovery_eligible=False)
                loaded = Store(Path(d), project_id="P", run_id="R").load("G")
                self.assertEqual(loaded["phase"], disposition)
                self.assertEqual(loaded["prior_phase"], "PREPARED")
                self.assertEqual(loaded["binding_digests"], {"evidence":"c"*64})
                self.assertFalse(loaded["recovery_eligible"])
                self.assertEqual(tx["transaction_sha256"], loaded["transaction_sha256"])

    def test_unknown_transaction_schema_fails_closed(self):
        Store, Error = self.api()
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d), project_id="P", run_id="R")
            tx = store.create(gate_id="G", authority_core_sha256="a"*64, contract_sha256="b"*64)
            path = store.path("G")
            raw = path.read_text(encoding="utf-8").replace("orchestration.gate-continuation-transaction.v1", "unknown.v9")
            path.write_text(raw, encoding="utf-8")
            with self.assertRaisesRegex(Error, "schema"):
                store.load("G")

if __name__ == "__main__": unittest.main()
