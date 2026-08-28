from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from runtime.orchestrator.resume_store import ResumeStore, ResumeStoreError, RunBinding


A = "a" * 64
B = "b" * 64
C = "c" * 64


class ResumeStoreTests(unittest.TestCase):
    def binding(self) -> RunBinding:
        return RunBinding("project", "GATE-1", "G1-LV3-1", "run-1", A, B, "main", "1" * 40, C, {"app/a.py": A})

    def test_append_only_checkpoint_survives_process_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding = self.binding()
            store = ResumeStore(directory, binding)
            first = store.append("PACKAGE", A)
            checkpoint = store.append("CHECKPOINT", B, checkpoint=True)
            restarted = ResumeStore(directory, binding)
            outcome = restarted.resume(binding, {"app/a.py": A})
            self.assertEqual(outcome["status"], "RESUME_READY")
            self.assertEqual(outcome["checkpoint"]["event_sha256"], checkpoint["event_sha256"])
            self.assertEqual(outcome["last_event_sha256"], checkpoint["event_sha256"])
            self.assertEqual(first["previous_event_sha256"], None)

    def test_binding_drift_is_blocked_for_every_bound_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding = self.binding()
            store = ResumeStore(directory, binding)
            store.append("CHECKPOINT", A, checkpoint=True)
            mutations = {
                "branch": "other", "head": "2" * 40, "requirements_sha256": B,
                "plan_sha256": C, "artifact_sha256": A,
            }
            for field, value in mutations.items():
                with self.subTest(field=field), self.assertRaisesRegex(ResumeStoreError, "binding drift"):
                    store.resume(replace(binding, **{field: value}), {"app/a.py": A})

    def test_owned_file_drift_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding = self.binding()
            store = ResumeStore(directory, binding)
            store.append("CHECKPOINT", A, checkpoint=True)
            with self.assertRaisesRegex(ResumeStoreError, "owned-file content drift"):
                store.resume(binding, {"app/a.py": B})

    def test_event_tamper_is_detected_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding = self.binding()
            store = ResumeStore(directory, binding)
            store.append("CHECKPOINT", A, checkpoint=True)
            path = Path(directory) / "project/GATE-1/G1-LV3-1/run-1/events/000001.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["lifecycle"] = "EXIT"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ResumeStoreError, "event SHA drift"):
                ResumeStore(directory, binding).resume(binding, {"app/a.py": A})

    def test_remediation_binds_parent_and_changed_owned_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding = self.binding()
            store = ResumeStore(directory, binding)
            parent = store.append("REVIEW", A)
            remediation = store.append(
                "REMEDIATION", B,
                remediation_lineage={
                    "parent_event_sha256": parent["event_sha256"],
                    "before_owned_sha256": A,
                    "after_owned_sha256": B,
                },
                owned_content_sha256={"app/a.py": B},
            )
            store.append("CHECKPOINT", C, checkpoint=True, owned_content_sha256={"app/a.py": B})
            outcome = ResumeStore(directory, binding).resume(binding, {"app/a.py": B})
            self.assertEqual(remediation["remediation_lineage"]["parent_event_sha256"], parent["event_sha256"])
            self.assertEqual(outcome["checkpoint"]["owned_content_sha256"], {"app/a.py": B})

    def test_remediation_lineage_and_immutable_collision_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding = self.binding()
            store = ResumeStore(directory, binding)
            store.append("REVIEW", A)
            with self.assertRaisesRegex(ResumeStoreError, "parent lineage"):
                store.append("REMEDIATION", B, remediation_lineage={"parent_event_sha256": C, "before_owned_sha256": A, "after_owned_sha256": B})
            event = Path(directory) / "project/GATE-1/G1-LV3-1/run-1/events/000002.json"
            event.write_text("{}", encoding="utf-8")
            with self.assertRaises(ResumeStoreError):
                store.append("WORKER", A)


if __name__ == "__main__":
    unittest.main()
