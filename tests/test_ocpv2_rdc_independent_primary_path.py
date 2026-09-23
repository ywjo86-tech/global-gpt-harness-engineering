from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.approved_work_binding import ApprovedWorkBindingV1
from runtime.orchestrator.host_inspection_contract import (
    HOST_INSPECTION_RESULT_SCHEMA,
    HostInspectionResultV1,
)
from runtime.orchestrator.plan_activation import (
    PLAN_ACTIVATION_RESULT_SCHEMA_V1,
    PlanActivationResultV1,
    PlanActivationStore,
)
from runtime.orchestrator.remote_operator_outbox import (
    RemoteActivationProjectionV1,
    RemoteInspectionProjectionV1,
    RemoteResultOutbox,
)
from runtime.orchestrator.remote_operator_service import ControlMode, RemoteOperatorService
from tests.test_remote_operator_service import (
    FakeTransport,
    accepted,
    activation_envelope,
    full_plan_activation_envelope,
    envelope as existing_run_envelope,
    inspection_envelope,
    raw,
)


class FailingPublishTransport(FakeTransport):
    def publish_projection(self, projection):
        raise RuntimeError("simulated transport publish failure")


class RDCIndependentPrimaryPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.activation_state = self.root / "activation-state"
        self.activation_state.mkdir()
        self.outbox_root = self.root / "outbox"
        self.events: list[tuple[str, str]] = []
        self.registration_calls = 0
        self.full_plan_registration_calls = 0
        self.inspection_calls = 0
        self.resume_calls = 0
        self.binding = ApprovedWorkBindingV1(
            schema_version="orchestration.approved-work-binding.v1",
            activation_request_id="ACT-1",
            request_digest="1" * 64,
            project_alias="demo",
            project_id="P1",
            project_root="/project",
            approved_plan_path="PLAN.md",
            approved_plan_sha256="a" * 64,
            approved_spec_path="SPEC.md",
            approved_spec_sha256="b" * 64,
            requirement_artifact_path="requirements.json",
            requirement_artifact_sha256="c" * 64,
            approval_ref="approval:user",
            expected_branch="main",
            expected_head="d" * 40,
            task_ids=("T1",),
            runtime_release_digest="e" * 64,
            runtime_code_root="/runtime",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _registrar(self) -> PlanActivationResultV1:
        self.registration_calls += 1
        self.events.append(("register_new_job", "ACT-1"))
        return PlanActivationResultV1(
            schema_version=PLAN_ACTIVATION_RESULT_SCHEMA_V1,
            activation_request_id="ACT-1",
            project_id="P1",
            run_id="ACT-1",
            status="REGISTERED",
            canonical_job_path="/state/jobs/P1/ACT-1.job.json",
            authority_digest="f" * 64,
        )

    def _inspect(self, env):
        self.inspection_calls += 1
        self.events.append(("inspect", env.message_id))
        result = HostInspectionResultV1.ok(
            env.payload,
            {"clean": True, "source_head": "d" * 40, "freshness": "FRESH"},
        )
        projection = RemoteInspectionProjectionV1.from_result(result, message_id=env.message_id)
        RemoteResultOutbox(self.outbox_root).enqueue_projection(projection)
        return projection.to_dict()

    def _activate(self, env):
        store = PlanActivationStore(self.activation_state)
        receipt = store.record_or_load(
            request_id=env.payload.activation_request_id,
            binding=self.binding,
            registrar=self._registrar,
        )
        projection = RemoteActivationProjectionV1.from_receipt(receipt, message_id=env.message_id)
        RemoteResultOutbox(self.outbox_root).enqueue_projection(projection)
        return projection.to_dict()

    def _activate_full_plan(self, env):
        self.full_plan_registration_calls += 1
        self.events.append(("register_executable_full_plan", env.payload.activation_request_id))
        return {
            "schema_version": "orchestration.remote-full-plan-activation-status-projection.v1",
            "message_id": env.message_id,
            "activation_request_id": env.payload.activation_request_id,
            "project_alias": env.payload.project_alias,
            "request_digest": env.payload.request_digest,
            "result_class": "FULL_PLAN_REGISTERED",
        }

    def _resume(self, env, directive):
        self.resume_calls += 1
        self.events.append(("resume_existing_run", env.run_id))
        return {
            "result_class": "CANONICAL_FULL_PLAN_RESULT",
            "canonical_ref": f"run:{env.run_id}",
        }

    def _service(self, env, *, transport=None) -> tuple[RemoteOperatorService, FakeTransport]:
        transport = transport or FakeTransport((raw(f"RAW-{env.message_id}"),))
        service = RemoteOperatorService(
            transport=transport,
            decode_envelope=lambda _: env,
            ingress=lambda value: accepted(value),
            execute_authorized=self._resume,
            inspect_authorized=self._inspect,
            host_inspection_enabled=True,
            activate_authorized=self._activate,
            work_activation_enabled=True,
            activation_policy_ref="ACT-POLICY-1",
            activate_full_plan_authorized=self._activate_full_plan,
            full_plan_activation_enabled=True,
            full_plan_activation_policy_ref="FP-POLICY-1",
        )
        return service, transport

    def test_four_request_classes_do_not_cross_authority_boundaries(self) -> None:
        inspect_env = inspection_envelope()
        service, transport = self._service(inspect_env)
        inspected = service.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual((inspected.inspected, inspected.activated, inspected.executed), (1, 0, 0))
        self.assertEqual(self.events, [("inspect", inspect_env.message_id)])
        self.assertEqual(transport.projections[0]["schema_version"], "orchestration.remote-inspection-projection.v1")

        activation_env = activation_envelope()
        service, transport = self._service(activation_env)
        activated = service.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual((activated.inspected, activated.activated, activated.executed), (0, 1, 0))
        self.assertEqual(self.registration_calls, 1)
        self.assertEqual(transport.projections[0]["result_status"], "REGISTERED")

        full_plan_env = full_plan_activation_envelope()
        service, transport = self._service(full_plan_env)
        full_plan = service.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual(
            (full_plan.inspected, full_plan.activated, full_plan.full_plan_activated, full_plan.executed),
            (0, 0, 1, 0),
        )
        self.assertEqual(self.full_plan_registration_calls, 1)
        self.assertEqual(transport.projections[0]["result_class"], "FULL_PLAN_REGISTERED")

        resume_env = existing_run_envelope(state_change=True, task_id="T1", directive_id="D1")
        service, transport = self._service(resume_env)
        resumed = service.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual((resumed.inspected, resumed.activated, resumed.executed), (0, 0, 1))
        self.assertEqual(self.resume_calls, 1)
        self.assertEqual(self.registration_calls, 1)
        self.assertEqual(transport.projections[0]["result_class"], "CANONICAL_FULL_PLAN_RESULT")
        self.assertEqual(
            self.events,
            [
                ("inspect", inspect_env.message_id),
                ("register_new_job", "ACT-1"),
                ("register_executable_full_plan", "FP-ACT-1"),
                ("resume_existing_run", "R1"),
            ],
        )

    def test_feature_isolation_blocks_activation_without_disabling_inspection(self) -> None:
        inspect_env = inspection_envelope()
        service, _ = self._service(inspect_env)
        self.assertEqual(service.poll_once(mode=ControlMode.ACTIVE).inspected, 1)

        activation_env = activation_envelope()
        transport = FakeTransport((raw("RAW-A-BLOCK"),))
        service = RemoteOperatorService(
            transport=transport,
            decode_envelope=lambda _: activation_env,
            ingress=lambda value: accepted(value),
            execute_authorized=self._resume,
            inspect_authorized=self._inspect,
            host_inspection_enabled=True,
            activate_authorized=self._activate,
            work_activation_enabled=False,
            activation_policy_ref="ACT-POLICY-1",
        )
        blocked = service.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual((blocked.activated, blocked.executed, blocked.blocked), (0, 0, 1))
        self.assertEqual(self.registration_calls, 0)
        self.assertEqual(transport.projections[0]["result_class"], "WORK_ACTIVATION_DISABLED")

    def test_sealed_inspection_republishes_after_transport_failure_without_reexecution(self) -> None:
        env = inspection_envelope()
        transport = FailingPublishTransport((raw("RAW-I-FAIL"),))
        service, _ = self._service(env, transport=transport)
        with self.assertRaisesRegex(RuntimeError, "publish failure"):
            service.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual(self.inspection_calls, 1)

        restarted = RemoteResultOutbox(self.outbox_root)
        pending = restarted.pending()
        self.assertEqual(len(pending), 1)
        published = []
        self.assertEqual(restarted.publish_pending(lambda item: published.append(item.to_dict())), 1)
        self.assertEqual(self.inspection_calls, 1)
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]["request_id"], env.payload.request_id)

    def test_activation_replay_after_publish_failure_does_not_register_second_job(self) -> None:
        env = activation_envelope()
        transport = FailingPublishTransport((raw("RAW-A-FAIL"),))
        service, _ = self._service(env, transport=transport)
        with self.assertRaisesRegex(RuntimeError, "publish failure"):
            service.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual(self.registration_calls, 1)

        restarted = RemoteResultOutbox(self.outbox_root)
        published = []
        self.assertEqual(restarted.publish_pending(lambda item: published.append(item.to_dict())), 1)
        self.assertEqual(self.registration_calls, 1)

        replay_transport = FakeTransport((raw("RAW-A-REPLAY"),))
        replay_service, _ = self._service(env, transport=replay_transport)
        replay = replay_service.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual(replay.activated, 1)
        self.assertEqual(self.registration_calls, 1)
        self.assertEqual(replay_transport.projections[0]["result_status"], "REGISTERED")

    def test_stale_observation_is_labeled_and_not_promoted_to_completion_authority(self) -> None:
        request = inspection_envelope().payload
        observed = HostInspectionResultV1.ok(
            request,
            {"source_head": "1" * 40, "clean": True, "freshness": "FRESH"},
        )
        stale = HostInspectionResultV1(
            schema_version=HOST_INSPECTION_RESULT_SCHEMA,
            request_id=observed.request_id,
            correlation_id=observed.correlation_id,
            project_alias=observed.project_alias,
            operation=observed.operation,
            request_digest=observed.request_digest,
            status="STALE",
            data={
                **dict(observed.data),
                "freshness": "STALE",
                "observed_source_head": "1" * 40,
                "current_source_head": "2" * 40,
            },
            error_code="",
        )
        projection = RemoteInspectionProjectionV1.from_result(stale, message_id="MSG-STALE")
        self.assertEqual(projection.status, "STALE")
        self.assertEqual(projection.data["source_head"], "1" * 40)
        self.assertEqual(projection.data["current_source_head"], "2" * 40)
        self.assertNotIn("result_class", projection.to_dict())
        self.assertNotIn("authority_digest", projection.to_dict())


if __name__ == "__main__":
    unittest.main()
