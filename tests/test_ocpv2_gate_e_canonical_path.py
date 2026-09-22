from __future__ import annotations

import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

from runtime.orchestrator.operator_control import OPERATOR_DIRECTIVE_SCHEMA
from runtime.orchestrator.production_execution_gateway import HOST_GATEWAY, LOCAL_CHILD
from runtime.orchestrator.production_full_plan_runner import ContinuationOwnerToken, ProductionFullPlanError
from runtime.orchestrator.remote_operator_envelope import (
    REMOTE_OPERATOR_ENVELOPE_SCHEMA,
    seal_remote_envelope,
    validate_remote_envelope,
)
from runtime.orchestrator.remote_operator_ingress import (
    RemoteExecutionGatewayError,
    execute_remote_action_through_canonical_full_plan,
)
from runtime.orchestrator.schemas import TaskSlice, WorkerRequest


EXPECTED_CONTINUATION = "b" * 64
EXPECTED_RUN_STATE = "c" * 64
EXPECTED_RUNTIME_RELEASE = "d" * 64
EXPECTED_HEAD = "e" * 40


def envelope():
    payload = {
        "schema_version": REMOTE_OPERATOR_ENVELOPE_SCHEMA,
        "message_id": "GATE-E-M1",
        "sequence": 5,
        "issued_at": "2026-09-22T00:00:00+00:00",
        "expires_at": "2026-09-22T01:00:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "GITHUB_CONTROL_V1",
            "channel_id": "PR:1",
            "source_actor_id": "235775273",
            "source_message_id": "500",
        },
        "project_id": "P1",
        "run_id": "R1",
        "task_id": "LV1",
        "task_execution_id": "E1",
        "gate_id": "G1",
        "operator_directive": {
            "schema_version": OPERATOR_DIRECTIVE_SCHEMA,
            "project_id": "P1",
            "run_id": "R1",
            "task_id": "LV1",
            "task_execution_id": "E1",
            "current_stage": "PREPARE",
            "requested_next_stage": "ACTION",
            "required_capabilities": ["filesystem_write"],
            "state_change_required": True,
            "input_artifact_digests": ["a" * 64],
            "gate_id": "G1",
            "directive_id": "GATE-E-D1",
        },
        "directive_digest": "",
        "expected": {
            "continuation_state_sha256": EXPECTED_CONTINUATION,
            "continuation_owner_epoch": 7,
            "canonical_run_state_sha256": EXPECTED_RUN_STATE,
            "migration_id": "",
            "migration_transaction_sha256": "",
            "migration_phase": "",
            "qualification_evidence_sha256": "",
            "source_head": EXPECTED_HEAD,
            "runtime_release_digest": EXPECTED_RUNTIME_RELEASE,
        },
        "authorization": {
            "risk_envelope_ref": "RISK-E",
            "risk_envelope_digest": "f" * 64,
            "manual_action_authorization_digest": "",
        },
        "envelope_sha256": "",
    }
    return validate_remote_envelope(
        seal_remote_envelope(payload),
        now=datetime(2026, 9, 22, 0, 5, tzinfo=timezone.utc),
    )


def worker_request(*, run_id="R1", backend=HOST_GATEWAY, task_execution_id="E1"):
    task = TaskSlice(
        thread_id="LV1",
        assigned_agent="implementation-worker",
        input="sealed-package",
        expected_output="worker-result",
        validation_criteria=["focused", "full"],
        editable_scope=["runtime/owned.py"],
        forbidden_scope=[".git"],
        merge_point="G1",
        run_id=run_id,
        required_capabilities=["filesystem_write"],
        state_change_required=True,
        runtime_stage="ACTION",
        task_execution_id=task_execution_id,
    )
    return WorkerRequest(
        project_root="/canonical/project",
        task=task,
        contract_summary={"project_id": "P1", "gate_id": "G1", "lv_id": "LV1"},
        state_snapshot={"head": EXPECTED_HEAD},
        extra_context={
            "run_id": run_id,
            "gate_id": "G1",
            "lv_id": "LV1",
            "execution_backend": backend,
            "runtime_release_digest": EXPECTED_RUNTIME_RELEASE,
        },
    )


class FakeSupervisor:
    def __init__(self, *, epoch=7):
        self.epoch = epoch
        self.claims = 0
        self.transactions = 0
        self.epoch_checks = 0

    def claim_attested_continuation_owner(self, *, expected_gate_id):
        self.claims += 1
        return ContinuationOwnerToken("P1", "R1", expected_gate_id, self.epoch)

    @contextmanager
    def continuation_transaction(self, owner_token, transaction_store):
        self.transactions += 1
        yield

    def assert_current_epoch_locked(self, owner_token):
        self.epoch_checks += 1


class GateECanonicalPathTests(unittest.TestCase):
    def execute(self, *, supervisor=None, request=None, run_state=EXPECTED_RUN_STATE,
                source_head=EXPECTED_HEAD, runtime_release=EXPECTED_RUNTIME_RELEASE):
        env = envelope()
        sup = supervisor or FakeSupervisor()
        req = request or worker_request()
        return execute_remote_action_through_canonical_full_plan(
            env,
            env.operator_directive,
            supervisor=sup,
            transaction_store=object(),
            canonical_continuation_state_sha256=lambda: EXPECTED_CONTINUATION,
            canonical_run_state_sha256=lambda: run_state,
            current_source_head=lambda: source_head,
            current_runtime_release_digest=lambda: runtime_release,
            worker_request_resolver=lambda owner, envelope_value, directive: req,
        )

    def test_exact_binding_reaches_canonical_worker_once_inside_full_plan_transaction(self):
        sup = FakeSupervisor()
        with patch(
            "runtime.orchestrator.remote_operator_ingress.execute_production_worker",
            return_value={"status": "completed", "result_ref": "worker-result:1"},
        ) as worker:
            result = self.execute(supervisor=sup)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(worker.call_count, 1)
        self.assertEqual(worker.call_args.args[0].task.thread_id, "LV1")
        self.assertEqual(sup.claims, 1)
        self.assertEqual(sup.transactions, 1)
        self.assertGreaterEqual(sup.epoch_checks, 2)

    def test_owner_epoch_drift_blocks_before_worker_execution(self):
        sup = FakeSupervisor(epoch=8)
        with patch("runtime.orchestrator.remote_operator_ingress.execute_production_worker") as worker:
            with self.assertRaisesRegex(ProductionFullPlanError, "STALE_DIRECTIVE: continuation owner epoch mismatch"):
                self.execute(supervisor=sup)
        worker.assert_not_called()

    def test_runtime_binding_drift_blocks_before_owner_claim(self):
        sup = FakeSupervisor()
        with patch("runtime.orchestrator.remote_operator_ingress.execute_production_worker") as worker:
            with self.assertRaisesRegex(ProductionFullPlanError, "STALE_DIRECTIVE: source head mismatch"):
                self.execute(supervisor=sup, source_head="1" * 40)
        self.assertEqual(sup.claims, 0)
        worker.assert_not_called()

    def test_worker_request_identity_drift_blocks_before_worker_execution(self):
        request = worker_request(run_id="OTHER")
        with patch("runtime.orchestrator.remote_operator_ingress.execute_production_worker") as worker:
            with self.assertRaisesRegex(RemoteExecutionGatewayError, "WORKER_REQUEST_BINDING_MISMATCH"):
                self.execute(request=request)
        worker.assert_not_called()

    def test_non_host_gateway_worker_request_is_rejected(self):
        request = worker_request(backend=LOCAL_CHILD)
        with patch("runtime.orchestrator.remote_operator_ingress.execute_production_worker") as worker:
            with self.assertRaisesRegex(RemoteExecutionGatewayError, "HOST_GATEWAY_REQUIRED"):
                self.execute(request=request)
        worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
