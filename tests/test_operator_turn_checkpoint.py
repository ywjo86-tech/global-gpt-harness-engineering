from __future__ import annotations
import tempfile
import unittest
from pathlib import Path


class OperatorTurnCheckpointTests(unittest.TestCase):
    def api(self):
        try:
            from runtime.orchestrator.operator_turn_checkpoint import (
                OperatorTurnCheckpoint, OperatorTurnCheckpointStore, OperatorTurnCheckpointError,
            )
        except ModuleNotFoundError as exc:
            self.fail(f"operator turn checkpoint module missing: {exc}")
        return OperatorTurnCheckpoint, OperatorTurnCheckpointStore, OperatorTurnCheckpointError

    def fields(self):
        return dict(
            project_id="P", run_id="R", gate_id_or_stage="B2",
            authority_core_sha256="a"*64,
            checkpoint_kind="OPERATOR_HANDOFF_CHECKPOINT",
            owner_kind="OPERATOR_HANDOFF", owner_ref="ledger:B2",
            resume_contract_sha256="b"*64,
            last_semantic_progress_at="2026-09-21T00:00:00+00:00",
        )

    def test_checkpoint_is_evidence_only(self):
        Checkpoint,_,_=self.api()
        checkpoint=Checkpoint.create(**self.fields())
        self.assertEqual(checkpoint.control_authority,"NONE")
        self.assertFalse(hasattr(checkpoint,"resume"))
        self.assertFalse(hasattr(checkpoint,"dispatch"))
        checkpoint.validate()

    def test_store_round_trip_and_latest_pointer(self):
        Checkpoint,Store,_=self.api()
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td),project_id="P",run_id="R")
            checkpoint=Checkpoint.create(**self.fields())
            stored=store.save(checkpoint)
            loaded=store.load_latest()
            self.assertEqual(loaded.checkpoint_sha256,checkpoint.checkpoint_sha256)
            self.assertEqual(stored.checkpoint_sha256,checkpoint.checkpoint_sha256)

    def test_tampered_checkpoint_fails_closed(self):
        Checkpoint,_,Error=self.api()
        payload=Checkpoint.create(**self.fields()).to_dict()
        payload["owner_ref"]="tampered"
        with self.assertRaises(Error): Checkpoint.from_dict(payload)

    def test_unknown_kind_is_rejected(self):
        Checkpoint,_,Error=self.api()
        fields=self.fields(); fields["checkpoint_kind"]="UNKNOWN"
        with self.assertRaises(Error): Checkpoint.create(**fields)


if __name__ == "__main__": unittest.main()
