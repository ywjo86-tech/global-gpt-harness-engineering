from __future__ import annotations

import inspect
import unittest
from datetime import datetime, timezone

from runtime.orchestrator import remote_operator_service
from runtime.orchestrator.operator_control import OPERATOR_DIRECTIVE_SCHEMA
from runtime.orchestrator.remote_operator_envelope import (
    REMOTE_OPERATOR_ENVELOPE_SCHEMA,
    seal_remote_envelope,
    validate_remote_envelope,
)
from runtime.orchestrator.remote_operator_ingress import IngressDecision
from runtime.orchestrator.remote_operator_service import (
    CanaryScope,
    ControlMode,
    RemoteOperatorService,
    RemoteOperatorServiceError,
)
from runtime.orchestrator.remote_operator_transport import RawControlEnvelope


def envelope(*, state_change=True, task_id="T1", directive_id="D1"):
    current_stage = "PREPARE" if state_change else "ENTRY"
    next_stage = "ACTION" if state_change else "PREPARE"
    payload = {
        "schema_version": REMOTE_OPERATOR_ENVELOPE_SCHEMA,
        "message_id": f"MSG-{task_id}",
        "sequence": 1,
        "issued_at": "2026-09-21T00:00:00+00:00",
        "expires_at": "2026-09-21T01:00:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "TEST",
            "channel_id": "CTRL",
            "source_actor_id": "235775273",
            "source_message_id": "1",
        },
        "project_id": "P1",
        "run_id": "R1",
        "task_id": task_id,
        "task_execution_id": "E1",
        "gate_id": "G1",
        "operator_directive": {
            "schema_version": OPERATOR_DIRECTIVE_SCHEMA,
            "project_id": "P1",
            "run_id": "R1",
            "task_id": task_id,
            "task_execution_id": "E1",
            "current_stage": current_stage,
            "requested_next_stage": next_stage,
            "required_capabilities": ["filesystem_write"] if state_change else ["reasoning"],
            "state_change_required": state_change,
            "input_artifact_digests": ["a" * 64] if state_change else [],
            "gate_id": "G1",
            "directive_id": directive_id,
        },
        "directive_digest": "",
        "expected": {
            "continuation_state_sha256": "b" * 64 if state_change else "",
            "continuation_owner_epoch": 1 if state_change else 0,
            "canonical_run_state_sha256": "c" * 64 if state_change else "",
            "migration_id": "",
            "migration_transaction_sha256": "",
            "migration_phase": "",
            "qualification_evidence_sha256": "",
            "source_head": "e" * 40 if state_change else "",
            "runtime_release_digest": "d" * 64 if state_change else "",
        },
        "authorization": {
            "risk_envelope_ref": "RISK-1",
            "risk_envelope_digest": "f" * 64,
            "manual_action_authorization_digest": "",
        },
        "envelope_sha256": "",
    }
    return validate_remote_envelope(
        seal_remote_envelope(payload),
        now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc),
    )


def raw(message_id="RAW-1"):
    return RawControlEnvelope(
        source_repository_id=None,
        source_channel_id="TEST",
        source_actor_id="235775273",
        source_message_id=message_id,
        content=b"{}",
        received_at="2026-09-21T00:05:00+00:00",
    )


class FakeTransport:
    def __init__(self, items=()):
        self.items = tuple(items)
        self.receive_calls = 0
        self.acks = []
        self.projections = []

    def receive(self, *, limit=16):
        self.receive_calls += 1
        return self.items[:limit]

    def acknowledge_delivery(self, message_id):
        self.acks.append(message_id)

    def publish_projection(self, projection):
        self.projections.append(dict(projection))


def accepted(env):
    return IngressDecision(
        accepted=True,
        result_class="MESSAGE_RECEIVED",
        message_id=env.message_id,
        directive_digest=env.directive_digest,
        directive=env.operator_directive,
    )


def blocked(env, result_class="STALE_DIRECTIVE"):
    return IngressDecision(
        accepted=False,
        result_class=result_class,
        message_id=env.message_id,
        directive_digest=env.directive_digest,
        directive=None,
    )


class RemoteOperatorServiceTests(unittest.TestCase):
    def service(self, *, env, ingress_result=None, canary_scope=None):
        transport = FakeTransport((raw(),))
        executions = []

        def execute_authorized(envelope_value, directive):
            executions.append((envelope_value.message_id, directive.directive_id))
            return {"result_class": "CANONICAL_ACTION_COMPLETED", "canonical_ref": "effect:1"}

        service = RemoteOperatorService(
            transport=transport,
            decode_envelope=lambda raw_value: env,
            ingress=lambda envelope_value: ingress_result or accepted(envelope_value),
            execute_authorized=execute_authorized,
            canary_scope=canary_scope,
        )
        return service, transport, executions

    def test_disabled_does_not_receive(self):
        env = envelope()
        service, transport, executions = self.service(env=env)
        result = service.poll_once(mode=ControlMode.DISABLED)
        self.assertEqual(transport.receive_calls, 0)
        self.assertEqual(executions, [])
        self.assertEqual(result.received, 0)

    def test_observe_only_validates_and_projects_with_zero_mutation(self):
        env = envelope(state_change=True)
        service, transport, executions = self.service(env=env)
        result = service.poll_once(mode=ControlMode.OBSERVE_ONLY)
        self.assertEqual(result.validated, 1)
        self.assertEqual(result.executed, 0)
        self.assertEqual(executions, [])
        self.assertEqual(transport.projections[0]["result_class"], "OBSERVED")
        self.assertEqual(transport.acks, [env.message_id])

    def test_control_read_only_rejects_state_change_required_true(self):
        env = envelope(state_change=True)
        service, transport, executions = self.service(env=env)
        result = service.poll_once(mode=ControlMode.CONTROL_READ_ONLY)
        self.assertEqual(result.executed, 0)
        self.assertEqual(executions, [])
        self.assertEqual(transport.projections[0]["result_class"], "MODE_BLOCKED")

    def test_mutation_canary_accepts_only_exact_canary_scope(self):
        scope = CanaryScope(
            project_id="P1", run_id="R1", task_id="T1", gate_id="G1", directive_id="D1"
        )
        matching = envelope(state_change=True, task_id="T1", directive_id="D1")
        service, transport, executions = self.service(env=matching, canary_scope=scope)
        result = service.poll_once(mode=ControlMode.CONTROL_MUTATION_CANARY)
        self.assertEqual(result.executed, 1)
        self.assertEqual(executions, [(matching.message_id, "D1")])
        self.assertEqual(transport.projections[0]["result_class"], "CANONICAL_ACTION_COMPLETED")

        mismatch = envelope(state_change=True, task_id="T2", directive_id="D1")
        service2, transport2, executions2 = self.service(env=mismatch, canary_scope=scope)
        result2 = service2.poll_once(mode=ControlMode.CONTROL_MUTATION_CANARY)
        self.assertEqual(result2.executed, 0)
        self.assertEqual(executions2, [])
        self.assertEqual(transport2.projections[0]["result_class"], "CANARY_SCOPE_MISMATCH")

    def test_active_still_requires_normal_authorization_and_cas(self):
        env = envelope(state_change=True)
        service, transport, executions = self.service(env=env, ingress_result=blocked(env, "STALE_DIRECTIVE"))
        result = service.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual(result.executed, 0)
        self.assertEqual(executions, [])
        self.assertEqual(transport.projections[0]["result_class"], "STALE_DIRECTIVE")

    def test_unknown_mode_fails_closed(self):
        env = envelope()
        service, transport, executions = self.service(env=env)
        with self.assertRaisesRegex(RemoteOperatorServiceError, "UNKNOWN_MODE"):
            service.poll_once(mode="BOGUS")  # type: ignore[arg-type]
        self.assertEqual(transport.receive_calls, 0)
        self.assertEqual(executions, [])

    def test_import_has_no_systemd_git_or_package_side_effect(self):
        source = inspect.getsource(remote_operator_service)
        for forbidden in ("systemctl", "subprocess", "os.system", "pip install", "apt ", "git config"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
