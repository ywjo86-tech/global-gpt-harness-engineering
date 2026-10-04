from __future__ import annotations

import tempfile
import unittest

from runtime.ai_office.full_plan_activation import coordinate_approved_full_plan_activation
from runtime.ai_office.state_store import AIOfficeStateStore
from runtime.orchestrator.approved_full_plan_binding import (
    ExecutableAuthorityBundleV1,
    ValidatedGateAuthorityV1,
)


RUNTIME_RELEASE_DIGEST = "9" * 64


def legacy_bundle() -> ExecutableAuthorityBundleV1:
    gate = ValidatedGateAuthorityV1(
        gate_id="GATE-001",
        approval_evidence_path="/h/approval/a.json",
        approval_evidence_sha256="1" * 64,
        requirements_sha256="2" * 64,
        engine_requirement_evidence_path="/h/artifact/e.json",
        engine_requirement_evidence_sha256="3" * 64,
        project_requirement_evidence_paths_by_lv=(("TASK-001", "/p/docs/req.json", "4" * 64),),
        lv_order=("TASK-001",),
    )
    return ExecutableAuthorityBundleV1(
        schema_version="orchestration.executable-authority-bundle.v1",
        activation_request_id="AI-OFFICE-LEGACY-RUN-1",
        request_digest="5" * 64,
        project_alias="ai-office",
        project_id="AI_OFFICE_HARNESS_UPGRADE",
        project_root="/p",
        authority_root="/authority",
        mapping_root="/authority/mappings",
        approved_plan_path="docs/DEVELOPMENT_PLAN.txt",
        approved_plan_sha256="6" * 64,
        approved_spec_path="docs/spec.md",
        approved_spec_sha256="7" * 64,
        approval_ref="USER-AI-OFFICE-APPROVAL",
        expected_branch="implementation-ai-office-harness-ocp-20260924",
        expected_head="8" * 40,
        runtime_release_digest=RUNTIME_RELEASE_DIGEST,
        runtime_release_source_head="a" * 40,
        runtime_code_root="/runtime",
        gates=(gate,),
    )


class AIOfficeSuccessorCompatibilityTests(unittest.TestCase):
    def test_legacy_gate_serialization_omits_successor_prefix_fields(self) -> None:
        value = legacy_bundle()
        gate = value.to_dict()["gates"][0]

        self.assertNotIn("adopted_prefix_evidence_path", gate)
        self.assertNotIn("adopted_prefix_evidence_sha256", gate)
        self.assertEqual(value.to_dict()["runtime_release_digest"], RUNTIME_RELEASE_DIGEST)

    def test_exact_existing_run_rehydrates_without_rewrite_or_successor_injection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            value = legacy_bundle()
            store = AIOfficeStateStore(
                directory,
                project_id=value.project_id,
                run_id=value.activation_request_id,
            )

            first = coordinate_approved_full_plan_activation(value, office_store=store)
            snapshot_before = store.snapshot_path.read_bytes()
            journal_before = store.journal_path.read_bytes()

            second = coordinate_approved_full_plan_activation(value, office_store=store)

            self.assertEqual(first, second)
            self.assertEqual(store.load().revision, 1)
            self.assertEqual(store.snapshot_path.read_bytes(), snapshot_before)
            self.assertEqual(store.journal_path.read_bytes(), journal_before)
            self.assertEqual(value.runtime_release_digest, RUNTIME_RELEASE_DIGEST)

            persisted = (snapshot_before + journal_before).decode("utf-8")
            self.assertNotIn("runtime_release_digest", persisted)
            self.assertNotIn("adopted_prefix_evidence_path", persisted)
            self.assertNotIn("adopted_prefix_evidence_sha256", persisted)


if __name__ == "__main__":
    unittest.main()
