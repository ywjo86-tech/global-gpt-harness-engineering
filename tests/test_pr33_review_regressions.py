from __future__ import annotations

import hashlib
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path

from tests.capability_lifecycle_fixtures import active_record
from tests.reporting_fixtures import sample_report
from tests.test_operations_read_model import make_console

from runtime.ai_office.reporting_coordinator import ReportingCoordinator
from runtime.ai_office.report_receipts import ReportReceiptStore
from runtime.ai_office.report_sinks import (
    ReportSaveRequest,
    ReportSinkError,
    save_once,
)
from runtime.orchestrator.capability_lifecycle import (
    CapabilityLifecycleRecordV1,
)
from runtime.orchestrator.capability_lifecycle_store import (
    CapabilityLifecycleStore,
    CapabilityLifecycleStoreError,
)
from runtime.orchestrator.operations_read_model import (
    build_operations_read_model_from_console_snapshot,
    normalize_operations_state,
)
from runtime.jarvis_bridge.state_reader import (
    read_dashboard_state_projection_only,
)


def _record_with_id(contract_id: str) -> CapabilityLifecycleRecordV1:
    base = active_record()
    contract = replace(base.contract, contract_id=contract_id)
    return CapabilityLifecycleRecordV1.create(
        contract=contract,
        state=base.state,
        health=base.health,
        active_dependency_ids=base.active_dependency_ids,
        evidence_refs=base.evidence_refs,
    )


class _DigestSink:
    def __init__(self, destination: str) -> None:
        self.destination = destination

    def save(self, request: ReportSaveRequest):
        return {
            "remote_ref": f"{self.destination}:1",
            "digest": hashlib.sha256(
                request.content.encode()
            ).hexdigest(),
        }


class PR33ReviewRegressionTests(unittest.TestCase):

    def test_distinct_contract_ids_never_share_lifecycle_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = CapabilityLifecycleStore(Path(temporary))

            first = _record_with_id("cap:a/b")
            second = _record_with_id("cap:a:b")

            store.put(first)
            store.put(second)

            try:
                loaded_first = store.get("cap:a/b")
                loaded_second = store.get("cap:a:b")
            except CapabilityLifecycleStoreError as exc:
                self.fail(f"contract filename collision: {exc}")

            self.assertEqual(
                loaded_first.contract.contract_id,
                "cap:a/b",
            )
            self.assertEqual(
                loaded_second.contract.contract_id,
                "cap:a:b",
            )

    def test_concurrent_dependency_acquire_preserves_both_leases(self):
        class SlowReadStore(CapabilityLifecycleStore):
            def get(self, contract_id):
                result = super().get(contract_id)
                time.sleep(0.05)
                return result

        with tempfile.TemporaryDirectory() as temporary:
            store = SlowReadStore(Path(temporary))
            store.put(active_record())

            start = threading.Barrier(3)
            errors = []

            def worker(task_id):
                try:
                    start.wait()
                    store.acquire_dependency(
                        "cap:ui-design:1",
                        task_id,
                    )
                except Exception as exc:
                    errors.append(exc)

            t1 = threading.Thread(
                target=worker,
                args=("TASKEXEC-A",),
            )
            t2 = threading.Thread(
                target=worker,
                args=("TASKEXEC-B",),
            )

            t1.start()
            t2.start()
            start.wait()

            t1.join(timeout=5)
            t2.join(timeout=5)

            self.assertFalse(t1.is_alive())
            self.assertFalse(t2.is_alive())
            self.assertEqual(errors, [])

            final = store.get("cap:ui-design:1")

            self.assertEqual(
                set(final.active_dependency_ids),
                {"TASKEXEC-A", "TASKEXEC-B"},
            )

    def test_report_sink_receipt_binds_local_content_digest(self):
        class RemoteDigestSink:
            def save(self, request):
                return {
                    "remote_ref": "remote:RPT-1",
                    "digest": hashlib.sha256(
                        request.content.encode()
                    ).hexdigest(),
                }

        with tempfile.TemporaryDirectory() as temporary:
            request = ReportSaveRequest(
                "RPT-1",
                "LLMWIKI",
                "inbox/RPT-1.md",
                "body",
            )
            receipt = save_once(
                RemoteDigestSink(),
                request,
                ReportReceiptStore(temporary),
            )
            self.assertEqual(
                receipt.content_sha256,
                hashlib.sha256(b"body").hexdigest(),
            )

    def test_report_sink_rejects_remote_digest_mismatch(self):
        class RemoteDigestSink:
            def save(self, request):
                return {
                    "remote_ref": "remote:RPT-1",
                    "digest": "a" * 64,
                }

        with tempfile.TemporaryDirectory() as temporary:
            request = ReportSaveRequest(
                "RPT-1",
                "LLMWIKI",
                "inbox/RPT-1.md",
                "body",
            )

            with self.assertRaisesRegex(
                ReportSinkError,
                "sink digest mismatch",
            ):
                save_once(
                    RemoteDigestSink(),
                    request,
                    ReportReceiptStore(temporary),
                )

    def test_failed_execution_completion_report_never_becomes_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = replace(
                sample_report(),
                report_type="completion_report",
                execution_status="FAILURE",
            )

            coordinator = ReportingCoordinator(
                temporary,
                {
                    "NOTION": _DigestSink("NOTION"),
                    "LLMWIKI": _DigestSink("LLMWIKI"),
                },
            )

            outcome = coordinator.record(report)

            self.assertNotEqual(
                outcome.final_completion_status,
                "COMPLETE",
            )

    def test_ai_office_workflow_states_normalize_to_operational_states(self):
        expected = {
            "COMPLETE": "COMPLETED",
            "EXECUTION_IN_PROGRESS": "RUNNING",
            "RECOVERY_COORDINATION": "RECOVERING",
            "BLOCKED": "STALLED",
            "WAITING_APPROVAL": "WAITING_APPROVAL",
        }

        for raw_state, normalized in expected.items():
            with self.subTest(raw_state=raw_state):
                actual, _ = normalize_operations_state(
                    raw_state
                )
                self.assertEqual(actual, normalized)

    def test_console_snapshot_does_not_treat_project_phase_as_runtime_state(self):
        model = build_operations_read_model_from_console_snapshot(
            make_console(),
            {
                "current_phase":
                    "runtime orchestration smoke test",
                "next_step": "review evidence",
                "approval_required": False,
                "last_updated":
                    "2026-09-28T03:00:00+00:00",
            },
        )

        self.assertEqual(
            model.normalized_state,
            "RUNNING",
        )
        self.assertEqual(
            model.human_state,
            "작업 중",
        )

    def test_projection_only_reader_does_not_create_runtime_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "empty-project"
            project.mkdir()

            self.assertFalse(
                (project / "runtime").exists()
            )

            snapshot = read_dashboard_state_projection_only(
                project
            )

            self.assertEqual(
                snapshot["project_root"],
                str(project.resolve()),
            )
            self.assertFalse(
                (project / "runtime").exists()
            )


if __name__ == "__main__":
    unittest.main()
