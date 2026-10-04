from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from runtime.diagnostics.process_lifecycle import diagnose_process_lifecycle
from runtime.orchestrator.activation_receipt_resolution import resolve_activation_receipt_job
from runtime.orchestrator.durable_io import canonical_json_bytes, sha256_bytes
from runtime.orchestrator.full_plan_activation import FULL_PLAN_ACTIVATION_RECEIPT_SCHEMA_V1
from runtime.orchestrator.monitor_health import (
    load_attention_monitor_health,
    monitor_health_path,
    record_attention_monitor_health,
)
from runtime.orchestrator.production_execution_gateway import GatewayError, UnixSocketHostRunner
from runtime.orchestrator.wait_recovery import (
    PROVIDER_WAIT_POINTER_SCHEMA,
    _digest,
    load_active_provider_wait_recovery_evidence,
    retire_provider_wait_recovery_pointer,
)


class OperationalRepairContractTests(unittest.TestCase):
    def test_bounded_process_lifetime_becomes_orphan_suspected(self):
        result = diagnose_process_lifecycle(
            {
                "pid": 123,
                "owner_ref": "proof-owner",
                "owner_state_exists": True,
                "lock_exists": True,
                "expected_lifecycle_state": "HOST_GATEWAY_LISTENER",
                "last_semantic_progress": "",
                "process_kind": "HOST_GATEWAY",
                "age_seconds": 1900,
                "max_lifetime_seconds": 1860,
            },
            now=datetime.now(timezone.utc),
        )
        self.assertEqual(result.status, "ORPHAN_SUSPECTED")
        self.assertTrue(result.cleanup_authorization_required)

    def test_attention_monitor_health_receipt_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            receipt = record_attention_monitor_health(root, search_root=root)
            self.assertEqual(receipt.status, "HEALTHY")
            loaded = load_attention_monitor_health(
                monitor_health_path(root), now=datetime.now(timezone.utc), stale_after_seconds=180,
            )
            self.assertEqual(loaded.receipt_sha256, receipt.receipt_sha256)
            self.assertEqual(loaded.current_attention_count, 0)

    def test_activation_receipt_resolves_preserved_superseded_job(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            archived = root / "_workspace" / "archive" / "superseded-job-1.json"
            archived.parent.mkdir(parents=True)
            archived.write_text(json.dumps({
                "run_id": "R-SUPERSEDED",
                "authority_core_sha256": "c" * 64,
            }))
            unsigned = {
                "schema_version": FULL_PLAN_ACTIVATION_RECEIPT_SCHEMA_V1,
                "activation_request_id": "R-SUPERSEDED",
                "bundle_digest": "d" * 64,
                "result_status": "FULL_PLAN_REGISTERED",
                "canonical_job_path": str(root / "_workspace" / "production-full-plan-jobs" / "P" / "R-SUPERSEDED.job.json"),
                "run_id": "R-SUPERSEDED",
                "authority_digest": "c" * 64,
                "executable_authority_bundle_digest": "d" * 64,
            }
            receipt = {**unsigned, "activation_digest": sha256_bytes(canonical_json_bytes(unsigned))}
            receipt_path = root / "_workspace" / "full-plan-activation-receipts" / "R-SUPERSEDED.json"
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(json.dumps(receipt))
            resolution = resolve_activation_receipt_job(root, receipt_path)
            self.assertEqual(resolution.status, "ARCHIVED_SUPERSEDED")
            self.assertEqual(Path(resolution.resolved_job_path), archived.resolve())

    def test_provider_wait_pointer_is_retired_without_deleting_history(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            base = root / "_workspace" / "provider-wait" / "P1" / "R1--g1"
            base.mkdir(parents=True)
            pointer = {
                "schema_version": PROVIDER_WAIT_POINTER_SCHEMA,
                "project_id": "P1",
                "gate_run_id": "R1--g1",
                "lv_id": "L1",
                "evidence_file": "L1.json",
                "evidence_sha256": "a" * 64,
                "updated_at": "2026-10-04T00:00:00+00:00",
                "status": "ACTIVE",
                "control_authority": "NONE",
            }
            pointer["pointer_sha256"] = _digest(pointer)
            (base / "active.json").write_text(json.dumps(pointer))
            changed = retire_provider_wait_recovery_pointer(
                root, project_id="P1", gate_run_id="R1--g1",
                terminal_state_sha256="b" * 64, reason="FULL_PLAN_COMPLETED",
            )
            self.assertTrue(changed)
            self.assertTrue((base / "active.json").is_file())
            self.assertIsNone(load_active_provider_wait_recovery_evidence(
                root, project_id="P1", gate_run_id="R1--g1",
            ))
            retired = json.loads((base / "active.json").read_text())
            self.assertEqual(retired["status"], "RETIRED")
            self.assertEqual(retired["terminal_state_sha256"], "b" * 64)

    def test_host_runner_accept_timeout_is_bounded_and_socket_is_removed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            socket_path = root / "runner.sock"
            runner = UnixSocketHostRunner(socket_path, root / "ledger", broker_native=True)
            with self.assertRaisesRegex(GatewayError, "HOST_RUNNER_ACCEPT_TIMEOUT"):
                runner.serve_once(timeout=0.05)
            self.assertFalse(socket_path.exists())


if __name__ == "__main__":
    unittest.main()
