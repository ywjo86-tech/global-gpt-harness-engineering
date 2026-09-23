from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.host_inspection_contract import HostInspectionRequestV1, HostInspectionResultV1
from runtime.orchestrator.remote_operator_outbox import (
    RemoteOperatorOutboxError,
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


if __name__ == "__main__":
    unittest.main()
