from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.execution_lifecycle_v2 import resolve_lifecycle_mode
from runtime.orchestrator.ocpv2_runtime_service import (
    project_onboarding_enabled_from_environment,
)
from runtime.orchestrator.runtime_migration_handoff import (
    MigrationHandoffError,
    MigrationPhase,
    MigrationStore,
)


def _v1_spec() -> dict[str, str]:
    return {
        "migration_id": "G11-MIG-V1",
        "project_id": "P",
        "predecessor_run_id": "R1",
        "successor_run_id": "R2",
        "current_gate": "GATE-11",
        "resume_gate": "GATE-11",
        "approved_plan_sha256": "a" * 64,
        "approved_spec_sha256": "b" * 64,
        "authority_core_sha256": "c" * 64,
        "predecessor_state_sha256": "d" * 64,
        "source_head": "e" * 40,
        "target_release_head": "f" * 40,
        "target_manifest_sha256": "1" * 64,
        "successor_job_spec_sha256": "2" * 64,
    }


def _v2_spec() -> dict[str, str]:
    spec = _v1_spec()
    spec["migration_id"] = "G11-MIG-V2"
    spec["source_tree"] = "4" * 40
    spec["source_manifest_sha256"] = "5" * 64
    return spec


class HarnessLifecycleV2Gate11SuccessorQualificationTest(unittest.TestCase):
    def test_code_presence_does_not_migrate_existing_jobs_or_enable_onboarding(self) -> None:
        self.assertEqual(resolve_lifecycle_mode({}), "LEGACY")
        self.assertFalse(project_onboarding_enabled_from_environment({}))
        self.assertFalse(
            project_onboarding_enabled_from_environment(
                {"OCP_PROJECT_ONBOARDING_ENABLED": "true"}
            )
        )
        self.assertTrue(
            project_onboarding_enabled_from_environment(
                {"OCP_PROJECT_ONBOARDING_ENABLED": "1"}
            )
        )

    def test_successor_handoff_keeps_legacy_readable_and_v2_source_binding_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MigrationStore(Path(directory) / "migrations")
            legacy = store.create(_v1_spec())
            self.assertEqual(
                store.load(legacy.migration_id).schema_version,
                "orchestration.runtime-migration.v1",
            )

            store.rollback(legacy.migration_id, "qualification fixture complete")
            successor = store.create_v2(_v2_spec())
            self.assertEqual(successor.schema_version, "orchestration.runtime-migration.v2")
            self.assertEqual(successor.source_tree, "4" * 40)
            self.assertEqual(successor.source_manifest_sha256, "5" * 64)

            with self.assertRaises(MigrationHandoffError):
                store.advance(
                    successor.migration_id,
                    MigrationPhase.PREDECESSOR_QUIESCED,
                    updates={
                        "quiesced_state_sha256": "6" * 64,
                        "source_manifest_sha256": "0" * 64,
                    },
                )

    def test_successor_activation_remains_rollback_capable_before_predecessor_close(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MigrationStore(Path(directory) / "migrations")
            tx = store.create_v2(_v2_spec())
            tx = store.advance(
                tx.migration_id,
                MigrationPhase.PREDECESSOR_QUIESCED,
                updates={"quiesced_state_sha256": "6" * 64},
            )
            tx = store.advance(tx.migration_id, MigrationPhase.RUNTIME_ACTIVATED)
            tx = store.record_restored_runtime_evidence(tx.migration_id, "7" * 64)
            rolled_back = store.rollback(
                tx.migration_id, "gate11 rollback qualification"
            )
            self.assertEqual(rolled_back.phase, MigrationPhase.ROLLED_BACK)
            self.assertEqual(rolled_back.source_manifest_sha256, "5" * 64)


if __name__ == "__main__":
    unittest.main()
