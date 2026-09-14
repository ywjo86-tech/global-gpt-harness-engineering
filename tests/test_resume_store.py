from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from runtime.orchestrator.resume_store import ResumeStore, ResumeStoreError, RunBinding, allowed_capability_transition


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

    def test_capability_checkpoint_uses_canonical_event_chain_and_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding = self.binding()
            store = ResumeStore(directory, binding)
            store.append("PACKAGE", A)
            checkpoint = store.append_capability_checkpoint(
                "RUNTIME_SELECTION_READY", requirement_digest=B,
                evidence_sha256=C, evidence_references={"attestation": C},
            )
            restarted = ResumeStore(directory, binding)
            outcome = restarted.resume_capability(
                binding, {"app/a.py": A}, requirement_digest=B,
                stage="RUNTIME_SELECTION_READY",
            )
            self.assertEqual(checkpoint["lifecycle"], "WORKER")
            self.assertEqual(checkpoint["checkpoint_payload"]["run_id"], binding.run_id)
            self.assertEqual(checkpoint["checkpoint_payload"]["reader_min_version"], "v1")
            self.assertEqual(outcome["checkpoint_payload"]["stage"], "RUNTIME_SELECTION_READY")
            self.assertEqual(outcome["checkpoint_payload"]["canonical_plan_sha256"], B)

    def test_capability_checkpoint_requirement_drift_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding = self.binding()
            store = ResumeStore(directory, binding)
            store.append_capability_checkpoint("REQUIREMENT_DERIVED", requirement_digest=B, evidence_sha256=C)
            with self.assertRaisesRegex(ResumeStoreError, "requirement drift"):
                ResumeStore(directory, binding).resume_capability(
                    binding, {"app/a.py": A}, requirement_digest=C,
                )

    def test_identical_capability_checkpoint_is_read_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding = self.binding(); store = ResumeStore(directory, binding)
            first = store.append_capability_checkpoint("REQUIREMENT_DERIVED", requirement_digest=B, evidence_sha256=C)
            second = store.append_capability_checkpoint("REQUIREMENT_DERIVED", requirement_digest=B, evidence_sha256=C)
            self.assertEqual(first["event_sha256"], second["event_sha256"])
            self.assertEqual(len(store.verify()), 1)

    def test_capability_stage_chain_is_ordered_and_reloadable(self) -> None:
        stages = ("REQUIREMENT_DERIVED", "INVENTORY_CHECKED", "DISCOVERY_COMPLETED")
        with tempfile.TemporaryDirectory() as directory:
            binding = self.binding(); store = ResumeStore(directory, binding)
            for index, stage in enumerate(stages):
                store.append_capability_checkpoint(stage, requirement_digest=B, evidence_sha256=chr(97 + index) * 64)
            restarted = ResumeStore(directory, binding)
            self.assertEqual([item["stage"] for item in restarted.capability_checkpoints()], list(stages))
            cursor = restarted.capability_resume_cursor()
            self.assertEqual(cursor["stage"], "DISCOVERY_COMPLETED")
            self.assertEqual(cursor["next_stage"], "RAW_CANDIDATE")

    def test_capability_stage_dependency_gap_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding = self.binding(); store = ResumeStore(directory, binding)
            store.append_capability_checkpoint("EVALUATED", requirement_digest=B, evidence_sha256=A)
            with self.assertRaisesRegex(ResumeStoreError, "stage dependency"):
                store.capability_checkpoints()

    def test_route_aware_capability_transitions_allow_fast_paths(self) -> None:
        self.assertTrue(allowed_capability_transition("EXISTING_PROJECT", None, "REQUIREMENT_DERIVED"))
        self.assertTrue(allowed_capability_transition("EXISTING_PROJECT", "REQUIREMENT_DERIVED", "INVENTORY_CHECKED"))
        self.assertTrue(allowed_capability_transition("EXISTING_PROJECT", "INVENTORY_CHECKED", "RUNTIME_SELECTION_READY"))
        self.assertFalse(allowed_capability_transition("EXISTING_PROJECT", "INVENTORY_CHECKED", "DISCOVERY_COMPLETED"))

    def test_route_switch_and_rewind_fail_closed(self) -> None:
        self.assertFalse(allowed_capability_transition("EXISTING_AGENT", "INVENTORY_CHECKED", "INSTALL_COMPLETED"))
        self.assertFalse(allowed_capability_transition("DISCOVERED_PROJECT_INSTALL", "EVALUATED", "DISCOVERY_COMPLETED"))

    def test_effect_intent_and_receipt_are_append_only_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding = self.binding(); store = ResumeStore(directory, binding)
            intent = store.append_effect_intent(effect_id=A, stage="INSTALL", target=".agents/skills/demo",
                                                requirement_digest=B, evidence_sha256=C)
            same_intent = store.append_effect_intent(effect_id=A, stage="INSTALL", target=".agents/skills/demo",
                                                     requirement_digest=B, evidence_sha256=C)
            self.assertEqual(intent["event_sha256"], same_intent["event_sha256"])
            receipt = store.append_effect_receipt(effect_id=A, stage="INSTALL", target=".agents/skills/demo",
                                                  requirement_digest=B, evidence_sha256=C,
                                                  receipt={"status": "INSTALL_COMPLETED"})
            same_receipt = store.append_effect_receipt(effect_id=A, stage="INSTALL", target=".agents/skills/demo",
                                                       requirement_digest=B, evidence_sha256=C,
                                                       receipt={"status": "INSTALL_COMPLETED"})
            self.assertEqual(receipt["event_sha256"], same_receipt["event_sha256"])
            self.assertEqual([r["stage_payload"]["effect"]["state"] for r in store.effect_records(A)],
                             ["EFFECT_INTENT", "EFFECT_RECEIPT"])

    def test_run_lease_and_compare_append_reject_stale_writer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding = self.binding(); store = ResumeStore(directory, binding)
            first = store.append("PACKAGE", A, expected_previous_event_digest=None)
            with self.assertRaisesRegex(ResumeStoreError, "stale expected"):
                store.append("PREFLIGHT", B, expected_previous_event_digest=C)
            with store.run_lease():
                second = store.append("PREFLIGHT", B, expected_previous_event_digest=first["event_sha256"])
            self.assertEqual(second["previous_event_sha256"], first["event_sha256"])


if __name__ == "__main__":
    unittest.main()
