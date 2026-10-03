from __future__ import annotations
import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator.gate_orchestrator import _codex_eligibility_override, execute_gate
from runtime.orchestrator.production_canonical_authority import (
    ProductionCanonicalAuthorityError,
    _canonical_materialization_created_at,
    build_production_canonical_worker_authority_provider,
    production_canonical_package_identity,
)

class ProductionCanonicalProviderWiringTests(unittest.TestCase):
    def test_execute_gate_exposes_injected_readiness_inputs(self):
        sig = inspect.signature(execute_gate)
        self.assertIn("codex_auth_readiness", sig.parameters)
        self.assertIn("codex_readiness_recheck_probes", sig.parameters)
        self.assertIsNone(sig.parameters["codex_auth_readiness"].default)
        self.assertIsNone(sig.parameters["codex_readiness_recheck_probes"].default)


    def test_missing_precollected_codex_readiness_preserves_auto_detection(self):
        self.assertIsNone(_codex_eligibility_override(None))
        class Ready:
            auth_status = "READY"
        class NotReady:
            auth_status = "NOT_READY"
        self.assertIs(_codex_eligibility_override(Ready()), True)
        self.assertIs(_codex_eligibility_override(NotReady()), False)

    def test_package_identity_is_deterministic(self):
        kwargs = dict(
            project_id="wallet-affiliate-collector",
            gate_id="G1",
            lv_id="LV3-5",
            run_id="run-provider",
        )
        first = production_canonical_package_identity(**kwargs)
        second = production_canonical_package_identity(**kwargs)
        self.assertEqual(first, second)
        self.assertEqual(first[1], 1)
        self.assertTrue(first[0].startswith("PKG-"))

    def test_materialization_timestamp_is_create_once_across_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = _canonical_materialization_created_at(
                root,
                project_id="wallet-affiliate-collector",
                gate_id="G1",
                lv_id="LV3-5",
                run_id="run-provider",
                preferred_created_at_utc="2026-09-10T08:00:00Z",
            )
            second = _canonical_materialization_created_at(
                root,
                project_id="wallet-affiliate-collector",
                gate_id="G1",
                lv_id="LV3-5",
                run_id="run-provider",
                preferred_created_at_utc="2026-09-10T09:00:00Z",
            )
            self.assertEqual(first, "2026-09-10T08:00:00Z")
            self.assertEqual(second, first)

    def test_dynamic_provider_uses_none_satisfied_for_verified_historical_recertification(self):
        unsigned = {
            "schema_version": "orchestration.historical-lv-recertification.v1",
            "project_id": "PROJECT",
            "gate_id": "GATE-R02",
            "lv_id": "TASK-R02",
            "plan_sha256": "1" * 64,
            "current_approval_id": "new-approval",
            "historical_run_id": "old-run",
            "historical_approval_id": "old-approval",
            "historical_approval_record_hash": "2" * 64,
            "checkpoint_commit": "a" * 40,
            "current_head": "b" * 40,
            "handoff_sha256": "3" * 64,
            "exit_evidence_sha256": "4" * 64,
            "owned_files": ["runtime/orchestrator/x.py"],
        }
        recert = dict(unsigned)
        recert["record_sha256"] = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        provider = build_production_canonical_worker_authority_provider(
            codex_auth_readiness=None,
            readiness_recheck_probes=None,
            router_decision=None,
            satisfied_recertification=recert,
            verify_git_provenance=False,
        )
        manifest = {
            "approval_id": "new-approval",
            "source_head": "b" * 40,
            "tool_authorization_projection": {
                "operation_class_ids": ["PROJECT_OWNED_FILE_WRITE"],
                "worker_task_id": "TASK-R02",
                "package_binding_sha256": "5" * 64,
            },
            "tool_authorization_projection_sha256": "6" * 64,
            "active_tool_authorization_contracts": [],
            "owned_files": ["runtime/orchestrator/x.py"],
        }
        approved = SimpleNamespace(allowed_capabilities=("PROJECT_OWNED_FILE_WRITE",))
        with patch(
            "runtime.orchestrator.production_canonical_authority.derive_approved_task_from_lv_manifest",
            return_value=approved,
        ):
            value = provider(
                mode="normal",
                project_root=Path("/tmp/project"),
                harness_root=Path("/tmp/harness"),
                package_root=Path("/tmp/package"),
                parent_package_root=Path("/tmp/package"),
                manifest=manifest,
                recovery_package=None,
                recovery_preflight=None,
                requirements_sha256="7" * 64,
                project_id="PROJECT",
                gate_id="GATE-R02",
                lv_id="TASK-R02",
                run_id="new-run",
                canonical_plan_sha256="1" * 64,
            )
        binding = value["canonical_authority_binding"]
        self.assertEqual(binding["execution_obligation"], "NONE_SATISFIED")
        self.assertEqual(
            binding["satisfied_recertification"]["checkpoint_commit"], "a" * 40
        )

    def test_provider_missing_readiness_fails_before_any_probe(self):
        provider = build_production_canonical_worker_authority_provider(
            codex_auth_readiness=None,
            readiness_recheck_probes=None,
            verify_git_provenance=False,
        )
        with self.assertRaises(ProductionCanonicalAuthorityError) as caught:
            provider(
                mode="normal",
                project_root=Path("/tmp/project"),
                harness_root=Path("/tmp/harness"),
                package_root=Path("/tmp/package"),
                parent_package_root=Path("/tmp/package"),
                manifest={},
                recovery_package=None,
                recovery_preflight=None,
                requirements_sha256="1" * 64,
                project_id="wallet-affiliate-collector",
                gate_id="G1",
                lv_id="LV3-5",
                run_id="run-provider",
                canonical_plan_sha256="2" * 64,
            )
        self.assertEqual(
            caught.exception.reason_taxonomy,
            "PRODUCTION_CANONICAL_READINESS_REQUIRED",
        )

if __name__ == "__main__":
    unittest.main()
