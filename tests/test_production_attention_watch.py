from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.production_attention import AttentionOutbox
from runtime.orchestrator.production_attention_watch import discover_pending_attention


class ProductionAttentionWatchTests(unittest.TestCase):
    def test_discovers_registered_run_without_runtime_current_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness = root / "executor"; harness.mkdir()
            registry = harness / "_workspace/production-full-plan-jobs/P1"; registry.mkdir(parents=True)
            job = {"project_id": "P1", "run_id": "R1", "harness_root": str(harness)}
            (registry / "R1.job.json").write_text(json.dumps(job))
            run_base = harness / "_workspace/production-full-plan/P1/R1"; run_base.mkdir(parents=True)
            (run_base / "state.json").write_text(json.dumps({"state":"BLOCKED","current_gate":"G1","last_semantic_progress_at":"2026-09-19T00:00:00+00:00"}))
            AttentionOutbox(run_base, project_id="P1", run_id="R1").publish(kind="BLOCKED", state="BLOCKED", reason="fixture", gate_id="G1")
            rows = discover_pending_attention(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["project_id"], "P1")
            self.assertEqual(rows[0]["kind"], "BLOCKED")

    def test_synthesizes_read_only_liveness_loss_when_supervisor_is_silent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); harness = root / "executor"; harness.mkdir()
            registry = harness / "_workspace/production-full-plan-jobs/P1"; registry.mkdir(parents=True)
            (registry / "R2.job.json").write_text(json.dumps({"project_id":"P1","run_id":"R2","harness_root":str(harness)}))
            run_base = harness / "_workspace/production-full-plan/P1/R2"; run_base.mkdir(parents=True)
            (run_base / "state.json").write_text(json.dumps({
                "state":"RUNNING", "current_gate":"G1",
                "last_liveness_at":"2020-01-01T00:00:00+00:00",
                "last_semantic_progress_at":"2020-01-01T00:00:00+00:00",
            }))
            rows = discover_pending_attention(root, stale_after_seconds=1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["kind"], "SUPERVISOR_OR_WORKER_LIVENESS_LOST")
            self.assertTrue(rows[0]["synthetic_read_only"])


if __name__ == "__main__":
    unittest.main()
