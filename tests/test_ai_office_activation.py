from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from runtime.ai_office.activation import (
    AIActivationError,
    coordinate_approved_activation,
)
from runtime.ai_office.state_store import AIOfficeStateStore
from runtime.ai_office.workflow import WorkflowCoordinator
from runtime.orchestrator.approved_work_binding import ApprovedWorkBindingV1


def binding(**changes):
    values = {
        "schema_version": "orchestration.approved-work-binding.v1",
        "activation_request_id": "ACT-1", "request_digest": "a" * 64,
        "project_alias": "demo", "project_id": "project", "project_root": "/safe/project",
        "approved_plan_path": "IMPLEMENTATION_PLAN.md", "approved_plan_sha256": "b" * 64,
        "approved_spec_path": "SPEC.md", "approved_spec_sha256": "c" * 64,
        "requirement_artifact_path": "requirements.json", "requirement_artifact_sha256": "d" * 64,
        "approval_ref": "USER-APPROVAL-1", "expected_branch": "main", "expected_head": "e" * 40,
        "task_ids": ("G1", "G2"), "runtime_release_digest": "f" * 64,
        "runtime_code_root": "/safe/runtime",
    }
    values.update(changes)
    return ApprovedWorkBindingV1(**values)


class AIOfficeActivationTests(unittest.TestCase):
    def store(self, directory: str, value: ApprovedWorkBindingV1 | None = None) -> AIOfficeStateStore:
        item = value or binding()
        return AIOfficeStateStore(directory, project_id=item.project_id, run_id=item.activation_request_id)

    def test_request_local_approved_mapping_produces_provider_neutral_context(self):
        with tempfile.TemporaryDirectory() as directory:
            value = binding(); store = self.store(directory, value)
            context = coordinate_approved_activation(value, office_store=store)
            self.assertEqual(context.full_plan_plan_digest, value.approved_plan_sha256)
            self.assertEqual(context.full_plan_spec_digest, value.approved_spec_sha256)
            self.assertEqual(context.requirement_artifact_digest, value.requirement_artifact_sha256)
            self.assertTrue(context.requirement_envelope_digest)
            self.assertEqual(context.workflow_state, "INTAKE_READY")
            self.assertEqual(context.workflow_revision, 1)
            keys = set(context.to_dict())
            for forbidden in ("provider", "provider_ref", "model", "model_ref", "backend"):
                self.assertNotIn(forbidden, keys)

    def test_exact_existing_intake_state_rehydrates_without_second_office_run(self):
        with tempfile.TemporaryDirectory() as directory:
            value = binding(); store = self.store(directory, value)
            first = coordinate_approved_activation(value, office_store=store)
            second = coordinate_approved_activation(value, office_store=store)
            self.assertEqual(second, first)
            self.assertEqual(store.load().revision, 1)
            roots = list((Path(directory) / "_workspace" / "ai-office").iterdir())
            self.assertEqual(len(roots), 1)

    def test_conflicting_existing_workflow_revision_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            value = binding(); store = self.store(directory, value)
            coordinate_approved_activation(value, office_store=store)
            coordinator = WorkflowCoordinator(
                store, office_id="AI_OFFICE", department_id="HARNESS_ACTIVATION",
                schedule_ref="activation:ACT-1",
            )
            coordinator.transition("CONTEXT_ASSEMBLED", reason_ref="reason:other")
            with self.assertRaisesRegex(AIActivationError, "AI_ACTIVATION_CONFLICT"):
                coordinate_approved_activation(value, office_store=store)

    def test_conflicting_plan_identity_blocks_instead_of_rewriting_state(self):
        with tempfile.TemporaryDirectory() as directory:
            value = binding(); store = self.store(directory, value)
            store.initialize(approved_plan_ref="plan:" + "0" * 64, baseline_ref="head:" + value.expected_head)
            with self.assertRaisesRegex(AIActivationError, "AI_ACTIVATION_CONFLICT"):
                coordinate_approved_activation(value, office_store=store)
            self.assertEqual(store.load().approved_plan_ref, "plan:" + "0" * 64)

    def test_no_persistent_approved_register_or_execution_authority_is_added(self):
        import runtime.ai_office.activation as module
        source = inspect.getsource(module)
        self.assertNotIn("approved_register.json", source)
        self.assertNotIn("register_job(", source)
        self.assertNotIn("FullMCP", source)
        self.assertNotIn("provider_router", source)
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            coordinate_approved_activation(binding(), office_store=store)
            names = {path.name for path in store.root.iterdir()}
            self.assertEqual(names, {"snapshot.json", "transitions.jsonl", "state.lock"})


if __name__ == "__main__":
    unittest.main()
