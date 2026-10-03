from __future__ import annotations

import inspect
from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.durable_io import canonical_json_bytes, sha256_bytes
from runtime.orchestrator.full_plan_activation import FullPlanActivationReceiptV1
from runtime.orchestrator.host_inspection_contract import HostInspectionRequestV1, HostInspectionResultV1
from runtime.orchestrator.plan_activation import PlanActivationReceiptV1
from runtime.orchestrator.remote_operator_outbox import (
    RemoteOperatorOutboxError,
    RemoteActivationProjectionV1,
    RemoteFullPlanActivationProjectionV1,
    RemoteInspectionProjectionV1,
    RemoteResultOutbox,
    RemoteResultProjectionV1,
    parse_remote_projection,
)


def _projection(**changes):
    values = {
        "projection_id": "PROJ-1",
        "message_id": "MSG-1",
        "directive_digest": "a" * 64,
        "project_id": "P1",
        "run_id": "R1",
        "gate_id": "G1",
        "task_id": "T1",
        "canonical_state_ref": "state:R1",
        "canonical_state_sha256": "b" * 64,
        "effect_evidence_refs": ("effect:1",),
        "checkpoint_ref": "checkpoint:R1",
        "checkpoint_sha256": "c" * 64,
        "migration_transaction_sha256": "",
        "result_class": "CANONICAL_ACTION_COMPLETED",
        "result_summary": "done",
        "projected_at": "2026-09-21T00:00:00+00:00",
    }
    values.update(changes)
    return RemoteResultProjectionV1(**values)


class RemoteResultOutboxTests(unittest.TestCase):
    def test_projection_is_atomic_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = RemoteResultOutbox(root)
            projection = _projection()
            first.enqueue_projection(projection)
            second = RemoteResultOutbox(root)
            self.assertEqual(second.pending(), (projection,))

    def test_publish_failure_keeps_pending_and_retry_only_republishes(self):
        with tempfile.TemporaryDirectory() as td:
            outbox = RemoteResultOutbox(Path(td))
            projection = _projection()
            outbox.enqueue_projection(projection)
            publish_calls = []

            def failing(value):
                publish_calls.append(value.projection_id)
                raise RuntimeError("offline")

            with self.assertRaises(RuntimeError):
                outbox.publish_pending(failing)
            self.assertEqual([item.projection_id for item in outbox.pending()], ["PROJ-1"])

            outbox.publish_pending(lambda value: publish_calls.append(value.projection_id))
            self.assertEqual(publish_calls, ["PROJ-1", "PROJ-1"])
            self.assertEqual(outbox.pending(), ())

    def test_outbox_retry_after_restart_only_republishes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = RemoteResultOutbox(root)
            projection = _projection()
            first.enqueue_projection(projection)
            publish_calls = []

            restarted = RemoteResultOutbox(root)
            self.assertEqual(restarted.publish_pending(lambda value: publish_calls.append(value.projection_id)), 1)
            self.assertEqual(publish_calls, ["PROJ-1"])
            self.assertEqual(restarted.pending(), ())
            parameters = inspect.signature(RemoteResultOutbox.publish_pending).parameters
            self.assertEqual(tuple(parameters), ("self", "publisher"))

    def test_same_projection_id_and_digest_is_idempotent_but_changed_content_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            outbox = RemoteResultOutbox(Path(td))
            projection = _projection()
            outbox.enqueue_projection(projection)
            outbox.enqueue_projection(projection)
            with self.assertRaisesRegex(RemoteOperatorOutboxError, "conflicting projection"):
                outbox.enqueue_projection(_projection(result_summary="changed"))

    def test_completed_result_requires_canonical_evidence(self):
        with self.assertRaisesRegex(RemoteOperatorOutboxError, "canonical evidence"):
            _projection(
                canonical_state_ref="",
                canonical_state_sha256="",
                effect_evidence_refs=(),
                checkpoint_ref="",
                checkpoint_sha256="",
            )

    def test_mark_published_requires_matching_digest(self):
        with tempfile.TemporaryDirectory() as td:
            outbox = RemoteResultOutbox(Path(td))
            projection = _projection()
            outbox.enqueue_projection(projection)
            with self.assertRaisesRegex(RemoteOperatorOutboxError, "digest mismatch"):
                outbox.mark_published("PROJ-1", "0" * 64)
            self.assertEqual(len(outbox.pending()), 1)
            outbox.mark_published("PROJ-1", projection.projection_sha256)
            self.assertEqual(outbox.pending(), ())


class RemoteInspectionProjectionTests(unittest.TestCase):
    @staticmethod
    def result():
        request = HostInspectionRequestV1.from_mapping({
            "schema_version": "orchestration.host-inspection-request.v1",
            "request_id": "INSP-1", "correlation_id": "CORR-1",
            "project_alias": "demo", "operation": "git.status",
            "arguments": {}, "state_change_required": False,
        })
        return HostInspectionResultV1.ok(request, {"clean": True, "branch": "main"})

    def test_inspection_projection_round_trips_through_existing_outbox(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            projection = RemoteInspectionProjectionV1.from_result(self.result(), message_id="MSG-I1")
            first = RemoteResultOutbox(root)
            first.enqueue_projection(projection)
            restarted = RemoteResultOutbox(root)
            self.assertEqual(restarted.pending(), (projection,))
            self.assertEqual(parse_remote_projection(projection.to_dict()), projection)

    def test_publish_failure_retries_same_sealed_inspection_without_reexecution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); inspect_calls = ["INSP-1"]
            projection = RemoteInspectionProjectionV1.from_result(self.result(), message_id="MSG-I1")
            RemoteResultOutbox(root).enqueue_projection(projection)
            restarted = RemoteResultOutbox(root)
            with self.assertRaises(RuntimeError):
                restarted.publish_pending(lambda value: (_ for _ in ()).throw(RuntimeError("offline")))
            published = []
            self.assertEqual(restarted.publish_pending(lambda value: published.append(value)), 1)
            self.assertEqual(published, [projection])
            self.assertEqual(inspect_calls, ["INSP-1"])


class RemoteActivationProjectionTests(unittest.TestCase):
    @staticmethod
    def receipt():
        unsigned = {
            "schema_version": "orchestration.plan-activation-receipt.v1",
            "activation_request_id": "ACT-1", "binding_digest": "a" * 64,
            "result_status": "REGISTERED", "canonical_job_path": "/state/job.json",
            "run_id": "ACT-1", "authority_digest": "b" * 64,
        }
        return PlanActivationReceiptV1(
            **unsigned, activation_digest=sha256_bytes(canonical_json_bytes(unsigned)),
        )

    def test_activation_projection_round_trips_through_existing_outbox(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            projection = RemoteActivationProjectionV1.from_receipt(self.receipt(), message_id="MSG-A1")
            RemoteResultOutbox(root).enqueue_projection(projection)
            restarted = RemoteResultOutbox(root)
            self.assertEqual(restarted.pending(), (projection,))
            self.assertEqual(parse_remote_projection(projection.to_dict()), projection)

    def test_activation_projection_retry_does_not_require_registrar(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            projection = RemoteActivationProjectionV1.from_receipt(self.receipt(), message_id="MSG-A1")
            RemoteResultOutbox(root).enqueue_projection(projection)
            published = []
            self.assertEqual(RemoteResultOutbox(root).publish_pending(lambda p: published.append(p)), 1)
            self.assertEqual(published, [projection])


class RemoteFullPlanActivationProjectionTests(unittest.TestCase):
    @staticmethod
    def receipt():
        unsigned = {
            "schema_version": "orchestration.full-plan-activation-receipt.v1",
            "activation_request_id": "FP-ACT-1", "bundle_digest": "c" * 64,
            "result_status": "FULL_PLAN_REGISTERED", "canonical_job_path": "/state/full-plan.json",
            "run_id": "FP-ACT-1", "authority_digest": "d" * 64,
            "executable_authority_bundle_digest": "c" * 64,
        }
        return FullPlanActivationReceiptV1(
            **unsigned, activation_digest=sha256_bytes(canonical_json_bytes(unsigned)),
        )

    def test_full_plan_projection_carries_profile_and_bundle_digest(self):
        projection = RemoteFullPlanActivationProjectionV1.from_receipt(self.receipt(), message_id="MSG-FP-1")
        self.assertEqual(projection.activation_profile, "AUTO_RECONCILE_FULL_PLAN")
        self.assertEqual(projection.binding_digest, self.receipt().bundle_digest)
        self.assertEqual(projection.executable_authority_bundle_digest, self.receipt().executable_authority_bundle_digest)
        self.assertEqual(parse_remote_projection(projection.to_dict()), projection)

    def test_existing_outbox_rejects_conflicting_projection_id(self):
        with tempfile.TemporaryDirectory() as td:
            outbox = RemoteResultOutbox(Path(td))
            projection = RemoteFullPlanActivationProjectionV1.from_receipt(self.receipt(), message_id="MSG-FP-1")
            outbox.enqueue_projection(projection)
            conflict = replace(projection, authority_digest="0" * 64)
            with self.assertRaisesRegex(RemoteOperatorOutboxError, "conflicting projection ID"):
                outbox.enqueue_projection(conflict)

    def test_full_plan_projection_uses_existing_publish_retry_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            projection = RemoteFullPlanActivationProjectionV1.from_receipt(self.receipt(), message_id="MSG-FP-1")
            RemoteResultOutbox(root).enqueue_projection(projection)
            restarted = RemoteResultOutbox(root); published=[]
            self.assertEqual(restarted.publish_pending(lambda item: published.append(item)), 1)
            self.assertEqual(published, [projection]); self.assertEqual(restarted.pending(), ())


if __name__ == "__main__":
    unittest.main()
