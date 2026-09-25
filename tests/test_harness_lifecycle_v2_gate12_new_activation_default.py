from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.ai_office.full_plan_activation import AIFullPlanActivationContextV1
from runtime.orchestrator.approved_full_plan_binding import (
    ExecutableAuthorityBundleV1,
    ValidatedGateAuthorityV1,
)
from runtime.orchestrator.execution_lifecycle_v2 import (
    resolve_lifecycle_binding,
    validate_execution_authority_bundle,
)
from runtime.orchestrator.full_plan_activation import build_executable_full_plan_job


class HarnessLifecycleV2Gate12NewActivationDefaultTest(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[ExecutableAuthorityBundleV1, AIFullPlanActivationContextV1, Path]:
        project = root / "project"
        runtime = root / "runtime"
        state = root / "state"
        project.mkdir()
        runtime.mkdir()
        state.mkdir()

        gate = ValidatedGateAuthorityV1(
            gate_id="GATE-12",
            approval_evidence_path="approval.json",
            approval_evidence_sha256="a" * 64,
            requirements_sha256="b" * 64,
            engine_requirement_evidence_path="",
            engine_requirement_evidence_sha256="",
            project_requirement_evidence_paths_by_lv=(),
            lv_order=("TASK-001",),
            adopted_prefix_evidence_path="",
            adopted_prefix_evidence_sha256="",
        )
        bundle = ExecutableAuthorityBundleV1(
            schema_version="orchestration.executable-authority-bundle.v1",
            activation_request_id="G12-ACT-001",
            request_digest="c" * 64,
            project_alias="gate12-project",
            project_id="GATE12_PROJECT",
            project_root=str(project),
            authority_root=str(root / "authority"),
            mapping_root=str(root / "mappings"),
            approved_plan_path="plan.md",
            approved_plan_sha256="d" * 64,
            approved_spec_path="spec.md",
            approved_spec_sha256="e" * 64,
            approval_ref="USER-G12-APPROVAL",
            expected_branch="main",
            expected_head="f" * 40,
            runtime_release_digest="1" * 64,
            runtime_release_source_head="2" * 40,
            runtime_code_root=str(runtime),
            gates=(gate,),
        )
        context = AIFullPlanActivationContextV1(
            schema_version="ai-office.full-plan-activation-context.v1",
            activation_request_id=bundle.activation_request_id,
            project_id=bundle.project_id,
            office_run_id=bundle.activation_request_id,
            requirement_id="approved-full-plan:G12-ACT-001",
            requirement_envelope_digest="3" * 64,
            approved_plan_digest=bundle.approved_plan_sha256,
            approved_spec_digest=bundle.approved_spec_sha256,
            approval_ref=bundle.approval_ref,
            expected_head=bundle.expected_head,
            executable_authority_bundle_digest=bundle.bundle_digest,
            gate_ids=("GATE-12",),
            workflow_state="INTAKE_READY",
            workflow_revision=1,
            workflow_state_digest="4" * 64,
        )
        return bundle, context, state

    def _build(self, *, lifecycle_mode: str | None = None) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            bundle, context, state = self._fixture(Path(directory))
            kwargs = {}
            if lifecycle_mode is not None:
                kwargs["lifecycle_mode"] = lifecycle_mode
            with (
                patch(
                    "runtime.orchestrator.full_plan_activation._git_common_dir",
                    return_value="/tmp/gate12-git-common",
                ),
                patch(
                    "runtime.orchestrator.full_plan_activation.executor_runtime_identity",
                    return_value={"source_head": "5" * 40, "runtime_source_sha256": "6" * 64},
                ),
            ):
                job = build_executable_full_plan_job(
                    bundle,
                    ai_context=context,
                    harness_state_root=state,
                    **kwargs,
                )
            return job

    def test_new_full_plan_activation_defaults_to_v2(self) -> None:
        job = self._build()
        binding = resolve_lifecycle_binding(job)
        self.assertEqual(binding["lifecycle_mode"], "V2")
        self.assertTrue(binding["bound_at_activation"])
        self.assertFalse(binding["migration_allowed"])
        self.assertEqual(binding["runtime_release_digest"], "1" * 64)

        authority = validate_execution_authority_bundle(job)
        self.assertEqual(authority["project_id"], "GATE12_PROJECT")
        self.assertEqual(authority["run_id"], "G12-ACT-001")
        self.assertEqual(authority["activation_source_head"], "f" * 40)
        self.assertEqual(authority["runtime_release_digest"], "1" * 64)

    def test_explicit_legacy_fallback_leaves_job_unmigrated(self) -> None:
        job = self._build(lifecycle_mode="LEGACY")
        self.assertNotIn("lifecycle_binding", job)
        self.assertNotIn("execution_authority_bundle", job)
        self.assertEqual(resolve_lifecycle_binding(job)["lifecycle_mode"], "LEGACY")


if __name__ == "__main__":
    unittest.main()
