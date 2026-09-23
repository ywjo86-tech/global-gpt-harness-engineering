from __future__ import annotations

import inspect
import tempfile
import unittest

from runtime.ai_office.activation import AI_ACTIVATION_CONTEXT_SCHEMA_V1
from runtime.ai_office.full_plan_activation import (
    AIFullPlanActivationError,
    coordinate_approved_full_plan_activation,
)
from runtime.ai_office.state_store import AIOfficeStateStore
from runtime.ai_office.workflow import WorkflowCoordinator
from runtime.orchestrator.approved_full_plan_binding import (
    ExecutableAuthorityBundleV1, ValidatedGateAuthorityV1,
)


def bundle(**changes):
    gate = ValidatedGateAuthorityV1(
        gate_id="GATE-001", approval_evidence_path="/h/approval/a.json",
        approval_evidence_sha256="1"*64, requirements_sha256="2"*64,
        engine_requirement_evidence_path="/h/artifact/e.json",
        engine_requirement_evidence_sha256="3"*64,
        project_requirement_evidence_paths_by_lv=(("TASK-001", "/p/docs/req.json", "4"*64),),
        lv_order=("TASK-001",),
    )
    values = dict(
        schema_version="orchestration.executable-authority-bundle.v1",
        activation_request_id="FP-ACT-1", request_digest="5"*64,
        project_alias="demo", project_id="project", project_root="/p",
        authority_root="/authority", mapping_root="/authority/mappings",
        approved_plan_path="docs/DEVELOPMENT_PLAN.txt", approved_plan_sha256="6"*64,
        approved_spec_path="docs/spec.md", approved_spec_sha256="7"*64,
        approval_ref="USER-APPROVAL-1", expected_branch="main", expected_head="8"*40,
        runtime_release_digest="9"*64, runtime_release_source_head="a"*40,
        runtime_code_root="/runtime", gates=(gate,),
    )
    values.update(changes)
    return ExecutableAuthorityBundleV1(**values)


class AIFullPlanActivationTests(unittest.TestCase):
    def store(self, directory: str, value=None):
        item = value or bundle()
        return AIOfficeStateStore(directory, project_id=item.project_id, run_id=item.activation_request_id)

    def test_context_binds_executable_bundle_and_gate_order(self):
        with tempfile.TemporaryDirectory() as directory:
            value=bundle(); store=self.store(directory, value)
            context=coordinate_approved_full_plan_activation(value, office_store=store)
            self.assertEqual(context.executable_authority_bundle_digest, value.bundle_digest)
            self.assertEqual(context.gate_ids, ("GATE-001",))
            self.assertEqual(context.approved_plan_digest, value.approved_plan_sha256)
            self.assertEqual(context.approved_spec_digest, value.approved_spec_sha256)
            self.assertEqual(context.workflow_state, "INTAKE_READY")
            self.assertEqual(context.workflow_revision, 1)
            self.assertRegex(context.context_digest, r"^[0-9a-f]{64}$")

    def test_exact_existing_context_rehydrates_without_second_state(self):
        with tempfile.TemporaryDirectory() as directory:
            value=bundle(); store=self.store(directory, value)
            first=coordinate_approved_full_plan_activation(value, office_store=store)
            second=coordinate_approved_full_plan_activation(value, office_store=store)
            self.assertEqual(first, second)
            self.assertEqual(store.load().revision, 1)

    def test_conflicting_existing_workflow_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            value=bundle(); store=self.store(directory, value)
            coordinate_approved_full_plan_activation(value, office_store=store)
            WorkflowCoordinator(store, office_id="AI_OFFICE", department_id="HARNESS_ACTIVATION", schedule_ref="activation:FP-ACT-1").transition(
                "CONTEXT_ASSEMBLED", reason_ref="reason:drift")
            with self.assertRaisesRegex(AIFullPlanActivationError, "AI_FULL_PLAN_ACTIVATION_CONFLICT"):
                coordinate_approved_full_plan_activation(value, office_store=store)

    def test_existing_v1_context_schema_is_unchanged(self):
        self.assertEqual(AI_ACTIVATION_CONTEXT_SCHEMA_V1, "ai-office.activation-context.v1")

    def test_module_has_no_registration_or_effect_authority(self):
        import runtime.ai_office.full_plan_activation as module
        source=inspect.getsource(module)
        for forbidden in ("register_job(", "FullMCP", "provider_router", "subprocess", "approved_register.json"):
            with self.subTest(forbidden=forbidden): self.assertNotIn(forbidden, source)


if __name__ == "__main__": unittest.main()
