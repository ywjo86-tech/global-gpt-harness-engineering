from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.read_only_host_diagnostic_contract import ReadOnlyDiagnosticResultV1
from runtime.orchestrator.remote_diagnostic_outbox import (
    RemoteDiagnosticOutbox,
    RemoteDiagnosticOutboxError,
    RemoteDiagnosticProjectionV1,
)


def _result(**changes):
    values = {
        "request_id": "REQ-1",
        "correlation_id": "CORR-1",
        "project_id": "P1",
        "root_id": "project",
        "operation_id": "repo.snapshot",
        "authorization_decision": "ALLOW",
        "captured_at": "2026-09-23T00:00:00+00:00",
        "freshness": "CURRENT",
        "source_sha": "a" * 40,
        "runtime_sha": "b" * 40,
        "data_class": "DIAG_SUMMARY",
        "redaction_applied": False,
        "truncated": False,
        "status": "OK",
        "error_class": "",
        "payload": {"head": "a" * 40, "stale": False},
    }
    values.update(changes)
    return ReadOnlyDiagnosticResultV1.build(**values)


def _projection(**changes):
    values = {
        "projection_id": "DIAG-PROJ-1",
        "message_id": "MSG-1",
        "directive_digest": "c" * 64,
        "project_id": "P1",
        "run_id": "R1",
        "gate_id": "G1",
        "task_id": "T1",
        "request_digest": "d" * 64,
        "diagnostic_result": _result(),
        "projected_at": "2026-09-23T00:01:00+00:00",
    }
    values.update(changes)
    return RemoteDiagnosticProjectionV1(**values)


class RemoteDiagnosticOutboxTests(unittest.TestCase):
    def test_pending_survives_restart(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            projection = _projection()
            RemoteDiagnosticOutbox(root).enqueue(projection)
            self.assertEqual(RemoteDiagnosticOutbox(root).pending(), (projection,))

    def test_exact_reenqueue_is_idempotent_but_conflicting_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            outbox = RemoteDiagnosticOutbox(Path(td))
            projection = _projection()
            outbox.enqueue(projection)
            outbox.enqueue(projection)
            with self.assertRaisesRegex(RemoteDiagnosticOutboxError, "conflicting projection"):
                outbox.enqueue(_projection(request_digest="e" * 64))

    def test_symlink_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "target"
            target.mkdir()
            link = base / "link"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(RemoteDiagnosticOutboxError, "unsafe outbox root"):
                RemoteDiagnosticOutbox(link)

    def test_publish_moves_only_after_publisher_success(self):
        with tempfile.TemporaryDirectory() as td:
            outbox = RemoteDiagnosticOutbox(Path(td))
            projection = _projection()
            outbox.enqueue(projection)
            calls = []

            def failing(value):
                calls.append(value.projection_id)
                raise RuntimeError("offline")

            with self.assertRaises(RuntimeError):
                outbox.publish_pending(failing)
            self.assertEqual(outbox.pending(), (projection,))
            self.assertEqual(calls, ["DIAG-PROJ-1"])

            self.assertEqual(outbox.publish_pending(lambda value: calls.append(value.projection_id)), 1)
            self.assertEqual(outbox.pending(), ())
            self.assertEqual(calls, ["DIAG-PROJ-1", "DIAG-PROJ-1"])

    def test_mark_published_requires_matching_projection_digest(self):
        with tempfile.TemporaryDirectory() as td:
            outbox = RemoteDiagnosticOutbox(Path(td))
            projection = _projection()
            outbox.enqueue(projection)
            with self.assertRaisesRegex(RemoteDiagnosticOutboxError, "digest mismatch"):
                outbox.mark_published(projection.projection_id, "0" * 64)
            self.assertEqual(outbox.pending(), (projection,))
            outbox.mark_published(projection.projection_id, projection.projection_sha256)
            self.assertEqual(outbox.pending(), ())

    def test_tampered_diagnostic_payload_hash_is_rejected(self):
        value = _projection().to_dict()
        value["diagnostic_result"]["payload"]["head"] = "f" * 40
        with self.assertRaisesRegex(RemoteDiagnosticOutboxError, "payload hash"):
            RemoteDiagnosticProjectionV1.from_mapping(value)


if __name__ == "__main__":
    unittest.main()
