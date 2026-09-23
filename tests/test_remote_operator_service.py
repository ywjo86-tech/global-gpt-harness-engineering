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
from runtime.orchestrator.host_inspection_contract import HostInspectionResultV1
from runtime.orchestrator.remote_control_envelope import (
    REMOTE_CONTROL_ENVELOPE_SCHEMA, RemoteControlEnvelopeV1,
    seal_remote_control_envelope, validate_remote_control_envelope,
)
from runtime.orchestrator.remote_operator_outbox import RemoteInspectionProjectionV1
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


def inspection_envelope():
    request = {
        "schema_version": "orchestration.host-inspection-request.v1",
        "request_id": "INSP-1", "correlation_id": "CORR-1",
        "project_alias": "demo", "operation": "git.status",
        "arguments": {}, "state_change_required": False,
    }
    payload = {
        "schema_version": REMOTE_CONTROL_ENVELOPE_SCHEMA,
        "request_kind": "HOST_INSPECTION", "message_id": "MSG-I1", "sequence": 1,
        "issued_at": "2026-09-21T00:00:00+00:00", "expires_at": "2026-09-21T01:00:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {"adapter_id": "TEST", "channel_id": "CTRL", "source_actor_id": "235775273", "source_message_id": "11"},
        "payload": request, "payload_digest": "",
        "authorization": {"inspection_policy_ref": "POLICY-1"}, "envelope_sha256": "",
    }
    return validate_remote_control_envelope(
        seal_remote_control_envelope(payload),
        now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc),
    )


def activation_envelope(policy_ref="ACT-POLICY-1"):
    request = {
        "schema_version": "orchestration.approved-work-activation-request.v1",
        "activation_request_id": "ACT-1", "project_alias": "demo",
        "approved_plan_path": "PLAN.md", "approved_plan_sha256": "a" * 64,
        "approved_spec_path": "SPEC.md", "approved_spec_sha256": "b" * 64,
        "requirement_artifact_path": "requirements.json", "requirement_artifact_sha256": "c" * 64,
        "approval_ref": "approval:user", "expected_branch": "main", "expected_head": "d" * 40,
        "task_ids": ["T1"], "runtime_release_digest": "e" * 64,
    }
    payload = {
        "schema_version": REMOTE_CONTROL_ENVELOPE_SCHEMA,
        "request_kind": "APPROVED_WORK_ACTIVATION", "message_id": "MSG-A1", "sequence": 2,
        "issued_at": "2026-09-21T00:00:00+00:00", "expires_at": "2026-09-21T01:00:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {"adapter_id": "TEST", "channel_id": "CTRL", "source_actor_id": "235775273", "source_message_id": "12"},
        "payload": request, "payload_digest": "",
        "authorization": {"activation_policy_ref": policy_ref}, "envelope_sha256": "",
    }
    return validate_remote_control_envelope(
        seal_remote_control_envelope(payload),
        now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc),
    )


def full_plan_activation_envelope(policy_ref="FP-POLICY-1"):
    request = {
        "schema_version": "orchestration.approved-full-plan-activation-request.v1",
        "activation_request_id": "FP-ACT-1", "project_alias": "demo",
        "approved_plan": {"path": "docs/PLAN.md", "sha256": "1" * 64},
        "approved_spec": {"path": "docs/SPEC.md", "sha256": "2" * 64},
        "expected_branch": "main", "expected_head": "3" * 40,
        "runtime_release_digest": "4" * 64, "approval_ref": "approval:user:full-plan",
        "gate_bindings": [{
            "gate_id": "GATE-001",
            "approval_evidence": {"path": "gate.json", "sha256": "5" * 64},
            "engine_requirement_evidence": {"path": "engine.json", "sha256": "6" * 64},
            "project_requirement_evidence_by_lv": [{"lv_id": "TASK-001", "path": "docs/req.json", "sha256": "7" * 64}],
        }],
    }
    payload = {
        "schema_version": REMOTE_CONTROL_ENVELOPE_SCHEMA,
        "request_kind": "APPROVED_FULL_PLAN_ACTIVATION", "message_id": "MSG-FP1", "sequence": 3,
        "issued_at": "2026-09-21T00:00:00+00:00", "expires_at": "2026-09-21T01:00:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {"adapter_id": "TEST", "channel_id": "CTRL", "source_actor_id": "235775273", "source_message_id": "13"},
        "payload": request, "payload_digest": "",
        "authorization": {"full_plan_activation_policy_ref": policy_ref}, "envelope_sha256": "",
    }
    return validate_remote_control_envelope(
        seal_remote_control_envelope(payload),
        now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc),
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


    def test_host_inspection_runs_in_observe_read_only_canary_and_active_without_mutation(self):
        for mode in (ControlMode.OBSERVE_ONLY, ControlMode.CONTROL_READ_ONLY, ControlMode.CONTROL_MUTATION_CANARY, ControlMode.ACTIVE):
            with self.subTest(mode=mode):
                env = inspection_envelope(); transport = FakeTransport((raw("RAW-I"),)); inspections = []; mutations = []
                def inspect_authorized(envelope_value: RemoteControlEnvelopeV1):
                    inspections.append(envelope_value.message_id)
                    result = HostInspectionResultV1.ok(envelope_value.payload, {"clean": True})
                    return RemoteInspectionProjectionV1.from_result(result, message_id=envelope_value.message_id).to_dict()
                service = RemoteOperatorService(
                    transport=transport, decode_envelope=lambda _: env,
                    ingress=lambda _: (_ for _ in ()).throw(AssertionError("inspection must not enter mutation ingress")),
                    execute_authorized=lambda *_: mutations.append("mutation"),
                    inspect_authorized=inspect_authorized, host_inspection_enabled=True,
                )
                result = service.poll_once(mode=mode)
                self.assertEqual(result.inspected, 1); self.assertEqual(result.executed, 0)
                self.assertEqual(inspections, ["MSG-I1"]); self.assertEqual(mutations, [])
                self.assertEqual(transport.projections[0]["schema_version"], "orchestration.remote-inspection-projection.v1")

    def test_host_inspection_feature_off_fails_closed_without_callback(self):
        env = inspection_envelope(); transport = FakeTransport((raw("RAW-I"),)); calls = []
        service = RemoteOperatorService(
            transport=transport, decode_envelope=lambda _: env, ingress=lambda _: None,
            execute_authorized=lambda *_: calls.append("mutation"),
            inspect_authorized=lambda _: calls.append("inspection"), host_inspection_enabled=False,
        )
        result = service.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual((result.inspected, result.executed, result.blocked), (0, 0, 1))
        self.assertEqual(calls, [])
        self.assertEqual(transport.projections[0]["result_class"], "HOST_INSPECTION_DISABLED")

    def test_host_inspection_failure_does_not_fall_through_to_mutation(self):
        env = inspection_envelope(); transport = FakeTransport((raw("RAW-I"),)); mutations = []
        service = RemoteOperatorService(
            transport=transport, decode_envelope=lambda _: env, ingress=lambda _: None,
            execute_authorized=lambda *_: mutations.append("mutation"),
            inspect_authorized=lambda _: (_ for _ in ()).throw(ValueError("inspection failed")),
            host_inspection_enabled=True,
        )
        result = service.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual((result.inspected, result.executed, result.blocked), (0, 0, 1))
        self.assertEqual(mutations, [])
        self.assertEqual(transport.projections[0]["result_class"], "HOST_INSPECTION_ERROR")

    def test_host_inspection_branch_has_no_execution_authority_imports(self):
        source = inspect.getsource(remote_operator_service)
        for forbidden in ("FullMCPRuntime", "ProcessService", "register_job(", "provider_router", "shell_execute"):
            with self.subTest(forbidden=forbidden): self.assertNotIn(forbidden, source)


    def test_work_activation_is_blocked_outside_active_mode(self):
        for mode in (ControlMode.OBSERVE_ONLY, ControlMode.CONTROL_READ_ONLY, ControlMode.CONTROL_MUTATION_CANARY):
            with self.subTest(mode=mode):
                env = activation_envelope(); transport = FakeTransport((raw("RAW-A"),)); activations = []; mutations = []
                service = RemoteOperatorService(
                    transport=transport, decode_envelope=lambda _: env,
                    ingress=lambda _: (_ for _ in ()).throw(AssertionError("activation must not enter V2 ingress")),
                    execute_authorized=lambda *_: mutations.append("mutation"),
                    activate_authorized=lambda e: activations.append(e.message_id) or {"schema_version": "activation", "result_class": "REGISTERED"},
                    work_activation_enabled=True, activation_policy_ref="ACT-POLICY-1",
                )
                result = service.poll_once(mode=mode)
                self.assertEqual((result.activated, result.executed, result.blocked), (0, 0, 1))
                self.assertEqual(activations, []); self.assertEqual(mutations, [])
                self.assertEqual(transport.projections[0]["result_class"], "MODE_BLOCKED")

    def test_active_work_activation_requires_feature_and_exact_policy(self):
        env = activation_envelope(); transport = FakeTransport((raw("RAW-A"),)); calls = []
        service = RemoteOperatorService(
            transport=transport, decode_envelope=lambda _: env, ingress=lambda _: None,
            execute_authorized=lambda *_: calls.append("mutation"),
            activate_authorized=lambda e: calls.append(e.message_id) or {"schema_version": "activation", "result_class": "REGISTERED"},
            work_activation_enabled=True, activation_policy_ref="ACT-POLICY-1",
        )
        result = service.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual((result.activated, result.executed, result.blocked), (1, 0, 0))
        self.assertEqual(calls, ["MSG-A1"]); self.assertEqual(transport.projections[0]["result_class"], "REGISTERED")

        blocked_transport = FakeTransport((raw("RAW-A2"),))
        blocked_service = RemoteOperatorService(
            transport=blocked_transport, decode_envelope=lambda _: env, ingress=lambda _: None,
            execute_authorized=lambda *_: calls.append("mutation"), activate_authorized=lambda _: calls.append("unexpected"),
            work_activation_enabled=True, activation_policy_ref="WRONG-POLICY",
        )
        blocked_result = blocked_service.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual(blocked_result.blocked, 1); self.assertEqual(calls, ["MSG-A1"])
        self.assertEqual(blocked_transport.projections[0]["result_class"], "ACTIVATION_AUTHORIZATION_MISMATCH")

    def test_activation_failure_never_falls_through_to_existing_run_mutation(self):
        env = activation_envelope(); transport = FakeTransport((raw("RAW-A"),)); mutations = []
        service = RemoteOperatorService(
            transport=transport, decode_envelope=lambda _: env, ingress=lambda _: None,
            execute_authorized=lambda *_: mutations.append("mutation"),
            activate_authorized=lambda _: (_ for _ in ()).throw(ValueError("activation failed")),
            work_activation_enabled=True, activation_policy_ref="ACT-POLICY-1",
        )
        result = service.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual((result.activated, result.executed, result.blocked), (0, 0, 1))
        self.assertEqual(mutations, []); self.assertEqual(transport.projections[0]["result_class"], "WORK_ACTIVATION_ERROR")


    def test_v1_enable_does_not_enable_executable_activation(self):
        env = full_plan_activation_envelope(); transport = FakeTransport((raw("RAW-FP"),)); calls=[]
        service = RemoteOperatorService(
            transport=transport, decode_envelope=lambda _: env, ingress=lambda _: None,
            execute_authorized=lambda *_: calls.append("mutation"),
            activate_authorized=lambda _: calls.append("v1"), work_activation_enabled=True,
            activation_policy_ref="ACT-POLICY-1",
            activate_full_plan_authorized=lambda _: calls.append("full-plan"),
            full_plan_activation_enabled=False, full_plan_activation_policy_ref="FP-POLICY-1",
        )
        result = service.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual((result.full_plan_activated, result.activated, result.executed, result.blocked), (0, 0, 0, 1))
        self.assertEqual(calls, [])
        self.assertEqual(transport.projections[0]["result_class"], "FULL_PLAN_ACTIVATION_DISABLED")

    def test_executable_activation_requires_active_mode_and_exact_dedicated_policy(self):
        for mode in (ControlMode.OBSERVE_ONLY, ControlMode.CONTROL_READ_ONLY, ControlMode.CONTROL_MUTATION_CANARY):
            with self.subTest(mode=mode):
                env=full_plan_activation_envelope(); transport=FakeTransport((raw("RAW-FP"),)); calls=[]
                service=RemoteOperatorService(
                    transport=transport, decode_envelope=lambda _: env, ingress=lambda _: None,
                    execute_authorized=lambda *_: calls.append("mutation"),
                    activate_full_plan_authorized=lambda _: calls.append("full-plan"),
                    full_plan_activation_enabled=True, full_plan_activation_policy_ref="FP-POLICY-1",
                )
                result=service.poll_once(mode=mode)
                self.assertEqual((result.full_plan_activated,result.blocked),(0,1)); self.assertEqual(calls,[])
                self.assertEqual(transport.projections[0]["result_class"],"MODE_BLOCKED")
        env=full_plan_activation_envelope(policy_ref="FP-POLICY-1"); transport=FakeTransport((raw("RAW-FP2"),)); calls=[]
        service=RemoteOperatorService(
            transport=transport, decode_envelope=lambda _: env, ingress=lambda _: None,
            execute_authorized=lambda *_: calls.append("mutation"),
            activate_full_plan_authorized=lambda _: calls.append("full-plan"),
            full_plan_activation_enabled=True, full_plan_activation_policy_ref="OTHER",
        )
        result=service.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual((result.full_plan_activated,result.blocked),(0,1)); self.assertEqual(calls,[])
        self.assertEqual(transport.projections[0]["result_class"],"FULL_PLAN_ACTIVATION_AUTHORIZATION_MISMATCH")

    def test_active_executable_activation_uses_only_dedicated_callback(self):
        env=full_plan_activation_envelope(); transport=FakeTransport((raw("RAW-FP"),)); calls=[]
        service=RemoteOperatorService(
            transport=transport, decode_envelope=lambda _: env,
            ingress=lambda _: (_ for _ in ()).throw(AssertionError("must not enter V2 ingress")),
            execute_authorized=lambda *_: calls.append("mutation"),
            activate_authorized=lambda _: calls.append("v1"), work_activation_enabled=True, activation_policy_ref="ACT-POLICY-1",
            activate_full_plan_authorized=lambda e: calls.append(("full-plan",e.message_id)) or {"schema_version":"full-plan","result_class":"FULL_PLAN_REGISTERED"},
            full_plan_activation_enabled=True, full_plan_activation_policy_ref="FP-POLICY-1",
        )
        result=service.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual((result.full_plan_activated,result.activated,result.executed,result.blocked),(1,0,0,0))
        self.assertEqual(calls,[("full-plan","MSG-FP1")]); self.assertEqual(transport.projections[0]["result_class"],"FULL_PLAN_REGISTERED")


if __name__ == "__main__":
    unittest.main()
